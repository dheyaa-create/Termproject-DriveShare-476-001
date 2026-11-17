"""
routes.py
=========
HTTP layer (Flask blueprints). Views are deliberately thin: they read the
request, call a service, and render a template or redirect. All business
rules live in ``driveshare/services`` and ``driveshare/patterns``.

Blueprints
----------
auth_bp  - register / login / logout / password recovery (Chain of Responsibility)
main_bp  - listings (Builder), search, booking, watches (Observer), messages,
           payments (Proxy), history, reviews, notifications
api_bp   - small JSON endpoints used by the JavaScript Mediator components

Request flow
------------
Each route acts as a controller: it reads trusted identity from ``g.user``,
gets the request-scoped database connection, delegates business rules to a
service, then returns a template, JSON response, or redirect. Expected
user-input errors become flash messages for HTML pages or structured errors
for the JSON API.
"""

from flask import (Blueprint, abort, flash, g, jsonify, redirect, render_template, request,
                   session, url_for)

from driveshare.database import get_db
from driveshare.patterns.car_builder import ListingValidationError
from driveshare.patterns.password_recovery import RecoveryRequest, build_recovery_chain
from driveshare.patterns.session_manager import SessionManager
from driveshare.services import auth_service as auth
from driveshare.services import booking_service as bookings
from driveshare.services import car_service as cars
from driveshare.services import community_service as community
from driveshare.services import notification_service as notes
from driveshare.services.auth_service import login_required

auth_bp = Blueprint("auth", __name__)
main_bp = Blueprint("main", __name__)
api_bp = Blueprint("api", __name__, url_prefix="/api")

# Errors raised by services that should be shown to the user as a flash message
USER_ERRORS = (ListingValidationError, bookings.BookingError, community.CommunityError,
               auth.AuthError, ValueError)


def _safe_next(target):
    """Allow only local redirects, preventing attacker-controlled destinations.

    Flask accepts absolute URLs in redirects. Requiring one leading slash and
    rejecting two leading slashes keeps a login redirect on this site.
    """
    return target if target and target.startswith("/") and not target.startswith("//") else None


# =========================================================================== #
# Authentication                                                              #
# =========================================================================== #
@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    """Render the registration form or create an account from its submission."""
    # Keep submitted values for a re-render after validation errors.
    form = request.form
    if request.method == "POST":
        try:
            # Compare the confirmation here; the service handles account data,
            # password policy, uniqueness, and security-question validation.
            if form.get("password") != form.get("confirm"):
                raise auth.AuthError("The two passwords do not match.")
            user_id = auth.register_user(
                get_db(), form.get("name"), form.get("email"), form.get("password"),
                [form.get(f"question{i}", "") for i in (1, 2, 3)],
                [form.get(f"answer{i}", "") for i in (1, 2, 3)])
            # Authenticate the new account immediately after successful creation.
            auth.login_user(user_id)
            flash("Welcome to DriveShare! Your account is ready.", "success")
            return redirect(url_for("main.index"))
        except auth.AuthError as exc:
            flash(str(exc), "danger")
    return render_template("auth/register.html", questions=auth.QUESTION_CHOICES, form=form)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """Authenticate credentials and redirect to a safe requested destination."""
    if request.method == "POST":
        # A missing account and a wrong password produce the same response.
        user = auth.authenticate(get_db(), request.form.get("email"), request.form.get("password"))
        if user:
            auth.login_user(user["id"])
            flash(f"Welcome back, {user['name']}!", "success")
            # Honor only a validated local destination; otherwise go home.
            return redirect(_safe_next(request.args.get("next")) or url_for("main.index"))
        flash("Invalid email or password.", "danger")
    return render_template("auth/login.html")


@auth_bp.route("/logout")
def logout():
    """Revoke the current session and return the user to the home page."""
    # This revokes the server-side token as well as clearing the browser cookie.
    auth.logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("main.index"))


@auth_bp.route("/recover", methods=["GET", "POST"])
def recover():
    """Step 1 of password recovery: identify the account by email."""
    if request.method == "POST":
        # Normalize email in the same way as registration and login.
        email = (request.form.get("email") or "").strip().lower()
        user = get_db().execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if user is None:
            flash("We could not find an account with that email.", "danger")
        else:
            # Save the account id needed by the next step, not the submitted email.
            session["recovery_user_id"] = user["id"]
            return redirect(url_for("auth.recover_answer"))
    return render_template("auth/recover.html")


@auth_bp.route("/recover/verify", methods=["GET", "POST"])
def recover_answer():
    """Step 2: answer all three questions; the Chain of Responsibility decides."""
    user_id = session.get("recovery_user_id")
    if not user_id:
        # Verification is valid only after the account-identification step.
        return redirect(url_for("auth.recover"))
    db = get_db()
    if request.method == "POST":
        if request.form.get("password") != request.form.get("confirm"):
            flash("The two passwords do not match.", "danger")
        else:
            # Each chain handler owns one check; the callback revokes sessions
            # after a successful password reset.
            chain = build_recovery_chain(db, on_reset=SessionManager().end_all_sessions_for)
            result = chain.handle(RecoveryRequest(
                user_id=user_id,
                answers=[request.form.get(f"answer{i}", "") for i in (1, 2, 3)],
                new_password=request.form.get("password", "")))
            if result.success:
                # Prevent reuse of the recovery target once reset succeeds.
                session.pop("recovery_user_id", None)
                flash("Your password has been reset. Please log in.", "success")
                return redirect(url_for("auth.login"))
            flash(result.message, "danger")
    return render_template("auth/recover_verify.html", questions=auth.get_questions(db, user_id))


# =========================================================================== #
# Home, search and car pages                                                  #
# =========================================================================== #
@main_bp.route("/")
def index():
    """Show the home page with a small set of highly rated active cars."""
    db = get_db()
    # Limit only after sorting so the featured set contains top-rated listings.
    featured = cars.search(db, sort="rating")[:6]
    owner_requests = (bookings.pending_bookings_as_owner(db, g.user["id"])
                      if g.user else [])
    return render_template("index.html", featured=featured, car_types=cars.car_types(db),
                           owner_requests=owner_requests)


@main_bp.route("/search")
def search():
    """Render server-side search results, displaying validation errors safely."""
    db = get_db()
    args = request.args
    try:
        # The service validates numeric filters and date windows; this route
        # turns expected input errors into a visible empty-results state.
        results = cars.search(db, args.get("location", ""), args.get("start", ""),
                              args.get("end", ""), args.get("max_price", ""),
                              args.get("car_type", ""), args.get("min_seats", ""),
                              args.get("keyword", ""), args.get("sort", "price_asc"))
    except USER_ERRORS as exc:
        flash(str(exc), "danger")
        results = []
    return render_template("search.html", results=results, args=args,
                           car_types=cars.car_types(db))


@main_bp.route("/cars/<int:car_id>")
def car_detail(car_id):
    """Display listing, availability, ratings, and the current user's watch."""
    db = get_db()
    car = cars.get_car(db, car_id)
    if car is None:
        abort(404)
    # Listing details are public, but watch state belongs to the current user.
    user = g.user
    avg, n = community.rating_summary(db, car["owner_id"])
    return render_template(
        "car_detail.html", car=car,
        windows=cars.availability_windows(db, car_id),
        booked=cars.booked_windows(db, car_id),
        watch=community.watch_for(db, user["id"], car_id) if user else None,
        owner_rating=avg, owner_reviews=n,
        reviews=community.reviews_about(db, car["owner_id"])[:5],
        prefill_start=request.args.get("start", ""), prefill_end=request.args.get("end", ""))


@main_bp.route("/users/<int:user_id>")
def profile(user_id):
    """Show a public profile with received reviews and active listings."""
    db = get_db()
    user = db.execute("SELECT id, name, created_at FROM users WHERE id = ?", (user_id,)).fetchone()
    if user is None:
        abort(404)
    # Reviews can be received by either role; only active listings are shown.
    avg, n = community.rating_summary(db, user_id)
    return render_template("profile.html", profile=user, rating=avg, review_count=n,
                           reviews=community.reviews_about(db, user_id),
                           listings=[c for c in cars.cars_of_owner(db, user_id) if c["is_active"]])


# =========================================================================== #
# Owner: listings                                                             #
# =========================================================================== #
@main_bp.route("/cars/new", methods=["GET", "POST"])
@login_required
def new_car():
    """Render the owner listing form or save a validated new car."""
    if request.method == "POST":
        try:
            # The Builder validates required fields before its product is saved.
            listing = cars.builder_from_form(g.user["id"], request.form).build()   # Builder
            car_id = cars.save_listing(get_db(), listing)
            flash(f"Your {listing.title} is now listed!", "success")
            return redirect(url_for("main.manage_car", car_id=car_id))
        except USER_ERRORS as exc:
            flash(str(exc), "danger")
    return render_template("owner/car_form.html", car=None, form=request.form)


@main_bp.route("/my-cars")
@login_required
def my_cars():
    """List the authenticated owner's car listings."""
    return render_template("owner/my_cars.html", cars=cars.cars_of_owner(get_db(), g.user["id"]))


@main_bp.route("/cars/<int:car_id>/manage", methods=["GET", "POST"])
@login_required
def manage_car(car_id):
    """Display management controls and apply one owner-selected listing action."""
    db = get_db()
    try:
        # Check ownership before rendering management data or applying changes.
        car = cars.owned_car(db, car_id, g.user["id"])
    except ListingValidationError:
        abort(404)
    if request.method == "POST":
        # One form submits an explicit action; the services still enforce the
        # action-specific validation and ownership rules.
        action = request.form.get("action")
        try:
            if action == "details":
                cars.update_details(db, car_id, g.user["id"], request.form)
                flash("Listing updated.", "success")
            elif action == "price":
                price = cars.update_price(db, car_id, g.user["id"], request.form.get("price_per_day"))
                flash(f"Price updated to ${price:.2f}/day. Watchers have been checked.", "success")
            elif action == "add_window":
                cars.add_availability(db, car_id, g.user["id"],
                                      request.form.get("start"), request.form.get("end"))
                flash("Availability added. Watchers have been checked.", "success")
            elif action == "remove_window":
                cars.remove_availability(db, car_id, g.user["id"], int(request.form.get("window_id")))
                flash("Availability window removed.", "info")
            elif action == "toggle":
                cars.set_active(db, car_id, g.user["id"], not car["is_active"])
                flash("Listing visibility changed.", "info")
        except USER_ERRORS as exc:
            flash(str(exc), "danger")
        # Post/Redirect/Get avoids repeating updates on a browser refresh.
        return redirect(url_for("main.manage_car", car_id=car_id))
    return render_template("owner/manage_car.html", car=car,
                           windows=cars.availability_windows(db, car_id),
                           booked=cars.booked_windows(db, car_id))


@main_bp.route("/cars/<int:car_id>/edit")
@login_required
def edit_car(car_id):
    """Open the shared listing form populated with the owner's current details."""
    try:
        car = cars.owned_car(get_db(), car_id, g.user["id"])
    except ListingValidationError:
        abort(404)
    return render_template("owner/car_form.html", car=car, form=car)


# =========================================================================== #
# Renter: booking & watching                                                  #
# =========================================================================== #
@main_bp.route("/cars/<int:car_id>/book", methods=["POST"])
@login_required
def book(car_id):
    """Submit a booking request for the authenticated renter."""
    try:
        # Derive renter identity from the authenticated session, never form data.
        bookings.create_booking(get_db(), car_id, g.user["id"],
                                request.form.get("start"), request.form.get("end"))
        flash("Booking request sent! The owner has been notified.", "success")
        return redirect(url_for("main.my_bookings"))
    except USER_ERRORS as exc:
        flash(str(exc), "danger")
        return redirect(url_for("main.car_detail", car_id=car_id))


@main_bp.route("/cars/<int:car_id>/watch", methods=["POST"])
@login_required
def watch(car_id):
    """Create or update a renter's price/date watch for a listing."""
    try:
        # The service replaces this renter's existing watch for the same car
        # and immediately evaluates whether the new criteria already match.
        matched = community.add_watch(get_db(), g.user["id"], car_id,
                                      request.form.get("max_price"),
                                      request.form.get("start"), request.form.get("end"))
        flash("Watch saved." + (" It already matches - check your notifications!" if matched
                                else " We'll notify you when it matches."), "success")
    except USER_ERRORS as exc:
        flash(str(exc), "danger")
    return redirect(url_for("main.car_detail", car_id=car_id))


@main_bp.route("/watches")
@login_required
def watches():
    """Display all watches saved by the authenticated renter."""
    return render_template("watches.html", watches=community.watches_of(get_db(), g.user["id"]))


@main_bp.route("/watches/<int:watch_id>/delete", methods=["POST"])
@login_required
def delete_watch(watch_id):
    """Remove a watch owned by the authenticated renter."""
    community.remove_watch(get_db(), g.user["id"], watch_id)
    flash("Watch removed.", "info")
    return redirect(url_for("main.watches"))


# =========================================================================== #
# Bookings, payments, history & reviews                                       #
# =========================================================================== #
@main_bp.route("/bookings")
@login_required
def my_bookings():
    """Show booking history in renter and owner views for the current user."""
    db = get_db()
    uid = g.user["id"]
    # Supply both perspectives; the selected tab is presentation state only.
    return render_template("bookings.html",
                           as_renter=bookings.bookings_as_renter(db, uid),
                           as_owner=bookings.bookings_as_owner(db, uid),
                           reviewed=community.reviewed_booking_ids(db, uid),
                           display_status=bookings.display_status,
                           tab=request.args.get(
                               "tab", "owner" if bookings.pending_bookings_as_owner(db, uid) else "renter"))


@main_bp.route("/bookings/<int:booking_id>/<action>", methods=["POST"])
@login_required
def booking_action(booking_id, action):
    """Dispatch an authorized booking lifecycle action to its service."""
    db = get_db()
    uid = g.user["id"]
    tab = "renter"
    try:
        # Services verify that the authenticated user has the correct role for
        # each state transition; the route dispatches and reports the result.
        if action in ("confirm", "decline"):
            tab = "owner"
            bookings.respond(db, booking_id, uid, action == "confirm", cars.make_publisher(db))
            flash(f"Booking {'confirmed' if action == 'confirm' else 'declined'}.", "success")
        elif action == "cancel":
            bookings.cancel(db, booking_id, uid, cars.make_publisher(db))
            flash("Booking cancelled.", "info")
        elif action == "pay":
            result = community.pay_booking(db, booking_id, uid, request.form.get("amount"),
                                           request.form.get("card_last4") or "4242")
            flash(f"Payment of ${result.amount:.2f} successful (ref {result.reference}).", "success")
        elif action == "review":
            tab = request.form.get("tab", "renter")
            community.add_review(db, booking_id, uid, request.form.get("rating"),
                                 request.form.get("comment"))
            flash("Thanks for your review!", "success")
        else:
            # Unknown action names must not silently appear successful.
            abort(404)
    except USER_ERRORS as exc:
        flash(str(exc), "danger")
    return redirect(url_for("main.my_bookings", tab=tab))


# =========================================================================== #
# Messaging & notifications                                                   #
# =========================================================================== #
@main_bp.route("/messages")
@login_required
def inbox():
    """Display the authenticated user's message conversations."""
    return render_template("messages/inbox.html",
                           conversations=community.conversations(get_db(), g.user["id"]))


@main_bp.route("/messages/<int:partner_id>", methods=["GET", "POST"])
@login_required
def conversation(partner_id):
    """Render a message thread or send a new message to its conversation partner."""
    db = get_db()
    partner = db.execute("SELECT id, name FROM users WHERE id = ?", (partner_id,)).fetchone()
    if partner is None or partner_id == g.user["id"]:
        # Missing users and self-conversations do not have a valid thread.
        abort(404)
    car_id = request.values.get("car_id", type=int)
    if request.method == "POST":
        try:
            # Keep body-length and recipient validation in the service layer.
            community.send_message(db, g.user["id"], partner_id, request.form.get("body"), car_id)
        except USER_ERRORS as exc:
            flash(str(exc), "danger")
        return redirect(url_for("main.conversation", partner_id=partner_id))
    return render_template("messages/thread.html", partner=partner,
                           messages=community.thread(db, g.user["id"], partner_id),
                           car=cars.get_car(db, car_id) if car_id else None)


@main_bp.route("/notifications")
@login_required
def notifications():
    """Show the user's notifications and mark the displayed set as read."""
    db = get_db()
    items = notes.list_for(db, g.user["id"])
    # Fetch first so the page can display the notifications before marking
    # them read for the next navigation-badge poll.
    notes.mark_all_read(db, g.user["id"])
    return render_template("notifications.html", items=items)


@main_bp.route("/about")
def about():
    """Render project information and the in-process active session count."""
    return render_template("about.html", sessions=SessionManager().active_session_count())


# =========================================================================== #
# JSON API used by the UI Mediator (static/js/mediator.js)                    #
# =========================================================================== #
@api_bp.route("/quote")
def quote():
    """Live price/availability check for the booking panel."""
    db = get_db()
    car = cars.get_car(db, request.args.get("car_id", type=int) or 0)
    if car is None:
        return jsonify(ok=False, reason="Car not found."), 404
    try:
        # This is an advisory check; create_booking repeats it under a write
        # lock when a renter actually submits the reservation.
        start, end = bookings.normalize_window(request.args.get("start"), request.args.get("end"))
    except USER_ERRORS as exc:
        return jsonify(ok=False, reason=str(exc))
    if not bookings.within_availability(db, car["id"], start, end):
        return jsonify(ok=False, reason="The owner has not offered the car for that whole period.")
    if bookings.conflicting_bookings(db, car["id"], start, end):
        return jsonify(ok=False, reason="Already booked for part of that period.")
    days, total = bookings.quote(car["price_per_day"], start, end)
    return jsonify(ok=True, days=days, total=total, price_per_day=car["price_per_day"])


@api_bp.route("/search")
def api_search():
    """Search results as JSON so the search page can refresh without reloading."""
    args = request.args
    try:
        # Reuse the same filters as the HTML search and return data for the
        # client-side Mediator to render without reloading the page.
        rows = cars.search(get_db(), args.get("location", ""), args.get("start", ""),
                           args.get("end", ""), args.get("max_price", ""),
                           args.get("car_type", ""), args.get("min_seats", ""),
                           args.get("keyword", ""), args.get("sort", "price_asc"))
    except USER_ERRORS as exc:
        return jsonify(ok=False, reason=str(exc), results=[])
    keys = ("id", "make", "model", "year", "mileage", "location", "price_per_day", "car_type",
            "seats", "transmission", "owner_name", "avg_rating")
    # Select only fields required by the UI; do not expose unrelated columns.
    results = [{k: r[k] for k in keys} for r in rows]
    for result in results:
        # Match the model-specific image used by server-rendered cards.
        result["image_url"] = url_for(
            "static", filename=cars.car_image_path(result["car_type"], result["make"], result["model"]))
    return jsonify(ok=True, results=results)


@api_bp.route("/notifications/unread")
def api_unread():
    """Return the unread count and newest unread message for navigation polling."""
    if g.user is None:
        # Public pages may poll too; respond without exposing account data.
        return jsonify(count=0)
    db = get_db()
    latest = db.execute("SELECT message FROM notifications WHERE user_id = ? AND is_read = 0 "
                        "ORDER BY id DESC LIMIT 1", (g.user["id"],)).fetchone()
    return jsonify(count=notes.unread_count(db, g.user["id"]),
                   latest=latest["message"] if latest else None)

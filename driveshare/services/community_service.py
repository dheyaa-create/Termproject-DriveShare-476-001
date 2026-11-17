"""
community_service.py
====================
Watches (renter side of the Observer pattern), direct messaging, payments
(through the Proxy) and reviews.
"""

from driveshare.patterns.observer import CarEvent
from driveshare.patterns.payment_proxy import PaymentProxy, PaymentRequest
from driveshare.services import booking_service as bookings
from driveshare.services import notification_service as notes
from driveshare.services.car_service import get_car, make_publisher


class CommunityError(ValueError):
    """Raised when a watch, message, payment, or review action is invalid."""

    pass


# --------------------------------------------------------------------------- #
# Watches                                                                     #
# --------------------------------------------------------------------------- #
def add_watch(db, renter_id, car_id, max_price="", start="", end=""):
    """
    Register (or replace) a renter's watch on a car, then immediately evaluate
    it once so the renter is told straight away if it already matches.
    """
    car = get_car(db, car_id)
    if car is None:
        raise CommunityError("Car not found.")
    if car["owner_id"] == renter_id:
        raise CommunityError("You cannot watch your own car.")
    price = float(max_price) if max_price not in (None, "") else None
    if price is not None and price <= 0:
        raise CommunityError("Target price must be positive.")
    if bool(start) != bool(end):
        raise CommunityError("Give both a start and an end date, or neither.")
    if start:
        start, end = bookings.normalize_window(start, end)
    if price is None and not start:
        raise CommunityError("Set a target price and/or the dates you need.")
    db.execute("INSERT INTO watches (renter_id, car_id, max_price, start_time, end_time) "
               "VALUES (?,?,?,?,?) ON CONFLICT(renter_id, car_id) DO UPDATE SET "
               "max_price=excluded.max_price, start_time=excluded.start_time, "
               "end_time=excluded.end_time, active=1",
               (renter_id, car_id, price, start or None, end or None))
    db.commit()
    watch_id = db.execute("SELECT id FROM watches WHERE renter_id=? AND car_id=?",
                          (renter_id, car_id)).fetchone()["id"]
    fired = make_publisher(db).publish(car_id, CarEvent.WATCH_CREATED, only_watch_id=watch_id)
    return bool(fired)


def remove_watch(db, renter_id, watch_id):
    """Delete a watch only when it belongs to the requesting renter."""
    db.execute("DELETE FROM watches WHERE id = ? AND renter_id = ?", (watch_id, renter_id))
    db.commit()


def watches_of(db, renter_id):
    """List a renter's watches with the car details needed by the UI."""
    return db.execute("SELECT w.*, c.make, c.model, c.year, c.price_per_day, c.location "
                      "FROM watches w JOIN cars c ON c.id = w.car_id WHERE w.renter_id = ? "
                      "ORDER BY w.id DESC", (renter_id,)).fetchall()


def watch_for(db, renter_id, car_id):
    """Return a renter's watch for one car, if one exists."""
    return db.execute("SELECT * FROM watches WHERE renter_id = ? AND car_id = ?",
                      (renter_id, car_id)).fetchone()


# --------------------------------------------------------------------------- #
# Messaging                                                                   #
# --------------------------------------------------------------------------- #
def send_message(db, sender_id, recipient_id, body, car_id=None):
    """Validate, persist, and notify the recipient about a direct message.

    The preview is shortened for notification display while the complete body
    remains in the message thread.
    """
    body = (body or "").strip()
    if not body:
        raise CommunityError("Message cannot be empty.")
    if len(body) > 2000:
        raise CommunityError("Message is too long (2000 characters max).")
    if sender_id == recipient_id:
        raise CommunityError("You cannot message yourself.")
    sender = db.execute("SELECT name FROM users WHERE id = ?", (sender_id,)).fetchone()
    if db.execute("SELECT 1 FROM users WHERE id = ?", (recipient_id,)).fetchone() is None:
        raise CommunityError("Recipient not found.")
    db.execute("INSERT INTO messages (sender_id, recipient_id, car_id, body) VALUES (?,?,?,?)",
               (sender_id, recipient_id, car_id, body))
    db.commit()
    preview = body if len(body) <= 60 else body[:57] + "..."
    notes.notify(db, recipient_id, "message", f"New message from {sender['name']}: \"{preview}\"",
                 f"/messages/{sender_id}")


def conversations(db, user_id):
    """Return one inbox row per partner, including latest message and unread count."""
    return db.execute(
        "SELECT u.id AS partner_id, u.name AS partner_name, MAX(m.id) AS last_id, "
        " (SELECT body FROM messages WHERE id = MAX(m.id)) AS last_body, "
        " (SELECT created_at FROM messages WHERE id = MAX(m.id)) AS last_at, "
        " SUM(CASE WHEN m.recipient_id = ? AND m.is_read = 0 THEN 1 ELSE 0 END) AS unread "
        "FROM messages m JOIN users u "
        "  ON u.id = CASE WHEN m.sender_id = ? THEN m.recipient_id ELSE m.sender_id END "
        "WHERE m.sender_id = ? OR m.recipient_id = ? "
        "GROUP BY u.id ORDER BY last_id DESC", (user_id,) * 4).fetchall()


def thread(db, user_id, partner_id):
    """Mark the partner's incoming messages read and return the full thread."""
    db.execute("UPDATE messages SET is_read = 1 WHERE sender_id = ? AND recipient_id = ?",
               (partner_id, user_id))
    db.commit()
    return db.execute(
        "SELECT m.*, c.make, c.model, c.year FROM messages m LEFT JOIN cars c ON c.id = m.car_id "
        "WHERE (sender_id = ? AND recipient_id = ?) OR (sender_id = ? AND recipient_id = ?) "
        "ORDER BY m.id", (user_id, partner_id, partner_id, user_id)).fetchall()


# --------------------------------------------------------------------------- #
# Payment (via Proxy)                                                         #
# --------------------------------------------------------------------------- #
def pay_booking(db, booking_id, payer_id, amount, card_last4="4242"):
    """
    Process payment through the validating Proxy and notify both parties.

    The UI's "Pay $X" button ends up here. This service never contacts the
    simulated gateway directly; a rejected proxy result becomes a
    ``CommunityError`` for the route to display.
    """
    proxy = PaymentProxy(db)
    result = proxy.process_payment(PaymentRequest(booking_id, payer_id, float(amount), card_last4))
    if not result.success:
        raise CommunityError(result.message)
    b = bookings.get_booking(db, booking_id)
    title = f"{b['year']} {b['make']} {b['model']}"
    notes.notify(db, result.payer_id, "payment",
                 f"Payment of ${result.amount:.2f} for the {title} succeeded (ref {result.reference}). "
                 f"Enjoy your trip!", "/bookings")
    notes.notify(db, result.payee_id, "payment",
                 f"You received ${result.amount:.2f} from {b['renter_name']} for the {title} "
                 f"(ref {result.reference}).", "/bookings")
    return result


# --------------------------------------------------------------------------- #
# Reviews                                                                     #
# --------------------------------------------------------------------------- #
def can_review(db, booking, user_id):
    """Check that the paid booking participant has not reviewed it already."""
    if booking["status"] != "paid":
        return False
    if user_id not in (booking["renter_id"], booking["owner_id"]):
        return False
    return db.execute("SELECT 1 FROM reviews WHERE booking_id = ? AND reviewer_id = ?",
                      (booking["id"], user_id)).fetchone() is None


def add_review(db, booking_id, reviewer_id, rating, comment):
    """Validate and store a participant's review, then notify its recipient."""
    b = bookings.get_booking(db, booking_id)
    if b is None or not can_review(db, b, reviewer_id):
        raise CommunityError("You cannot review this rental.")
    try:
        rating = int(rating)
    except (TypeError, ValueError):
        raise CommunityError("Please choose a rating.")
    if not 1 <= rating <= 5:
        raise CommunityError("Rating must be between 1 and 5.")
    reviewee = b["owner_id"] if reviewer_id == b["renter_id"] else b["renter_id"]
    db.execute("INSERT INTO reviews (booking_id, reviewer_id, reviewee_id, rating, comment) "
               "VALUES (?,?,?,?,?)", (booking_id, reviewer_id, reviewee, rating,
                                      (comment or "").strip() or None))
    db.commit()
    reviewer = db.execute("SELECT name FROM users WHERE id = ?", (reviewer_id,)).fetchone()
    notes.notify(db, reviewee, "review",
                 f"{reviewer['name']} left you a {rating}-star review.", f"/users/{reviewee}")


def reviews_about(db, user_id):
    """Return reviews received by a user, enriched with reviewer and car names."""
    return db.execute("SELECT r.*, u.name AS reviewer_name, c.make, c.model, c.year "
                      "FROM reviews r JOIN users u ON u.id = r.reviewer_id "
                      "JOIN bookings b ON b.id = r.booking_id JOIN cars c ON c.id = b.car_id "
                      "WHERE r.reviewee_id = ? ORDER BY r.id DESC", (user_id,)).fetchall()


def rating_summary(db, user_id):
    """Return the one-decimal average rating and review count for a user."""
    row = db.execute("SELECT ROUND(AVG(rating),1) AS avg, COUNT(*) AS n FROM reviews "
                     "WHERE reviewee_id = ?", (user_id,)).fetchone()
    return row["avg"], row["n"]


def reviewed_booking_ids(db, user_id):
    """Return booking ids that this user has already reviewed."""
    return {r[0] for r in db.execute("SELECT booking_id FROM reviews WHERE reviewer_id = ?",
                                     (user_id,)).fetchall()}

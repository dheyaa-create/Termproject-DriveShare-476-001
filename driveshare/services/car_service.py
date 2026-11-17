"""
car_service.py
==============
Persists ``CarListing`` products created by the Builder, lets owners manage
price/availability, implements search, and wires the Observer pattern
(``make_publisher``) to the database.
"""

from driveshare.patterns.car_builder import (CarListingBuilder, ListingValidationError,
                                             TIME_FMT, validate_price, validate_window)
from driveshare.patterns.observer import CarEvent, CarEventPublisher
from driveshare.services import booking_service as bookings
from driveshare.services import notification_service as notes


# --------------------------------------------------------------------------- #
# Observer wiring                                                             #
# --------------------------------------------------------------------------- #
def make_publisher(db):
    """Build the Observer publisher with database-backed collaborators.

    The nested callables adapt persistence and notification services to the
    small interfaces expected by ``CarEventPublisher``. Keeping that wiring
    here leaves the pattern itself independent of Flask and SQLite.
    """

    def load_car(car_id):
        """Return a plain-dictionary snapshot for Observer criteria checks."""
        row = db.execute("SELECT * FROM cars WHERE id = ?", (car_id,)).fetchone()
        return dict(row) if row else None

    def load_watches(car_id):
        """Load only active watches for the car being published."""
        return [dict(r) for r in db.execute(
            "SELECT * FROM watches WHERE car_id = ? AND active = 1", (car_id,)).fetchall()]

    def notifier(user_id, kind, message, link):
        """Persist a notification using the shared notification service."""
        notes.notify(db, user_id, kind, message, link)

    def on_triggered(watch):
        """Record when a watch last caused a notification."""
        db.execute("UPDATE watches SET last_notified = datetime('now') WHERE id = ?", (watch["id"],))
        db.commit()

    return CarEventPublisher(load_car, load_watches,
                             lambda cid, s, e: bookings.is_available(db, cid, s, e),
                             notifier, on_triggered)


# --------------------------------------------------------------------------- #
# Builder -> database                                                         #
# --------------------------------------------------------------------------- #
def builder_from_form(owner_id, form):
    """Translate submitted form fields into a configured listing builder.

    The builder owns field validation. Availability rows are paired by their
    form order, and empty rows are ignored by ``add_availability``.
    """
    b = (CarListingBuilder(owner_id)
         .set_model(form.get("make"), form.get("model"))
         .set_year(form.get("year"))
         .set_mileage(form.get("mileage"))
         .set_location(form.get("location"))
         .set_price_per_day(form.get("price_per_day"))
         .set_car_type(form.get("car_type"))
         .set_seats(form.get("seats"))
         .set_transmission(form.get("transmission"))
         .set_fuel_type(form.get("fuel_type"))
         .set_features(form.get("features"))
         .set_description(form.get("description")))
    for s, e in zip(form.getlist("avail_start"), form.getlist("avail_end")):
        b.add_availability(s, e)
    return b


def save_listing(db, listing):
    """Persist the listing and its availability rows, then return its id."""
    cur = db.execute(
        "INSERT INTO cars (owner_id, make, model, year, mileage, location, price_per_day, "
        "car_type, seats, transmission, fuel_type, features, description) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (listing.owner_id, listing.make, listing.model, listing.year, listing.mileage,
         listing.location, listing.price_per_day, listing.car_type, listing.seats,
         listing.transmission, listing.fuel_type, ", ".join(listing.features) or None,
         listing.description))
    car_id = cur.lastrowid
    for s, e in listing.availability:
        db.execute("INSERT INTO car_availability (car_id, start_time, end_time) VALUES (?,?,?)",
                   (car_id, s, e))
    db.commit()
    return car_id


# --------------------------------------------------------------------------- #
# Owner management                                                            #
# --------------------------------------------------------------------------- #
def get_car(db, car_id):
    """Load one car with the owner's display name, or return ``None``."""
    return db.execute("SELECT c.*, u.name AS owner_name FROM cars c "
                      "JOIN users u ON u.id = c.owner_id WHERE c.id = ?", (car_id,)).fetchone()


def owned_car(db, car_id, owner_id):
    """Load a car only if it belongs to ``owner_id``; otherwise raise."""
    car = get_car(db, car_id)
    if car is None or car["owner_id"] != owner_id:
        raise ListingValidationError("Listing not found.")
    return car


def update_details(db, car_id, owner_id, form):
    """Validate and update all editable listing details for the owner.

    Rebuilding through the Builder keeps create/edit validation consistent.
    A price-change event is published only when the price actually changes.
    """
    owned_car(db, car_id, owner_id)
    listing = builder_from_form(owner_id, form).build()
    old_price = get_car(db, car_id)["price_per_day"]
    db.execute("UPDATE cars SET make=?, model=?, year=?, mileage=?, location=?, price_per_day=?, "
               "car_type=?, seats=?, transmission=?, fuel_type=?, features=?, description=? "
               "WHERE id = ?",
               (listing.make, listing.model, listing.year, listing.mileage, listing.location,
                listing.price_per_day, listing.car_type, listing.seats, listing.transmission,
                listing.fuel_type, ", ".join(listing.features) or None, listing.description,
                car_id))
    db.commit()
    if listing.price_per_day != old_price:
        make_publisher(db).publish(car_id, CarEvent.PRICE_CHANGED)


def update_price(db, car_id, owner_id, new_price):
    """Validate and persist a new daily price, then re-evaluate car watches."""
    owned_car(db, car_id, owner_id)
    price = validate_price(new_price)          # same rule the Builder uses
    db.execute("UPDATE cars SET price_per_day = ? WHERE id = ?", (price, car_id))
    db.commit()
    make_publisher(db).publish(car_id, CarEvent.PRICE_CHANGED)
    return price


def add_availability(db, car_id, owner_id, start, end):
    """Add a validated availability window and notify matching watches."""
    owned_car(db, car_id, owner_id)
    s, e = validate_window(start, end)         # same rule the Builder uses
    db.execute("INSERT INTO car_availability (car_id, start_time, end_time) VALUES (?,?,?)",
               (car_id, s, e))
    db.commit()
    make_publisher(db).publish(car_id, CarEvent.AVAILABILITY_CHANGED)


def remove_availability(db, car_id, owner_id, window_id):
    """Remove an owner's window unless it contains an active reservation."""
    owned_car(db, car_id, owner_id)
    w = db.execute("SELECT * FROM car_availability WHERE id = ? AND car_id = ?",
                   (window_id, car_id)).fetchone()
    if w is None:
        raise ListingValidationError("Availability window not found.")
    if bookings.conflicting_bookings(db, car_id, w["start_time"], w["end_time"]):
        raise ListingValidationError("Cannot remove a window that contains active bookings.")
    db.execute("DELETE FROM car_availability WHERE id = ?", (window_id,))
    db.commit()


def set_active(db, car_id, owner_id, active):
    """Show or hide an owner's listing without deleting its history."""
    owned_car(db, car_id, owner_id)
    db.execute("UPDATE cars SET is_active = ? WHERE id = ?", (1 if active else 0, car_id))
    db.commit()


def availability_windows(db, car_id):
    """Return all owner-provided availability windows in chronological order."""
    return db.execute("SELECT * FROM car_availability WHERE car_id = ? ORDER BY start_time",
                      (car_id,)).fetchall()


def booked_windows(db, car_id):
    """Return active reservation windows used to mark dates unavailable."""
    return db.execute("SELECT start_time, end_time, status FROM bookings WHERE car_id = ? "
                      "AND status IN ('pending','confirmed','paid') ORDER BY start_time",
                      (car_id,)).fetchall()


def cars_of_owner(db, owner_id):
    """List a user's cars, newest listing first."""
    return db.execute("SELECT * FROM cars WHERE owner_id = ? ORDER BY id DESC", (owner_id,)).fetchall()


# --------------------------------------------------------------------------- #
# Search                                                                      #
# --------------------------------------------------------------------------- #
SORTS = {
    "price_asc": "c.price_per_day ASC",
    "price_desc": "c.price_per_day DESC",
    "year_desc": "c.year DESC",
    "rating": "avg_rating DESC",
}

# Shared, local listing imagery keeps the browse page, featured cards, and
# live-search results consistent without depending on external image hosts.
CAR_IMAGE_PATHS = {
    "sedan": "images/cars/sedan.jpg",
    "suv": "images/cars/suv.jpg",
    "electric": "images/cars/electric.jpg",
    "truck": "images/cars/truck.jpg",
}

CAR_MODEL_IMAGE_PATHS = {
    ("toyota", "camry"): "images/cars/2021-toyota-camry.jpg",
    ("toyota", "rav4 hybrid"): "images/cars/2023-toyota-rav4-hybrid.jpg",
    ("tesla", "model 3"): "images/cars/2022-tesla-model-3.jpg",
    ("honda", "civic"): "images/cars/2019-honda-civic.jpg",
    ("ford", "f-150"): "images/cars/2020-ford-f150.jpg",
}


def car_image_path(car_type, make=None, model=None):
    """Choose a bundled model photo, falling back to a vehicle-category image."""
    model_key = ((make or "").strip().lower(), (model or "").strip().lower())
    if model_key in CAR_MODEL_IMAGE_PATHS:
        return CAR_MODEL_IMAGE_PATHS[model_key]

    category = (car_type or "").strip().lower()
    if category in ("suv", "crossover"):
        image = CAR_IMAGE_PATHS["suv"]
    elif category in ("truck", "pickup"):
        image = CAR_IMAGE_PATHS["truck"]
    elif category in ("electric", "ev"):
        image = CAR_IMAGE_PATHS["electric"]
    else:
        image = CAR_IMAGE_PATHS["sedan"]
    return image
# Values in SORTS are fixed SQL fragments, not user-provided SQL. Search
# chooses from this allowlist to keep sorting flexible without SQL injection.


def search(db, location="", start="", end="", max_price="", car_type="", min_seats="",
           keyword="", sort="price_asc", exclude_owner=None):
    """
    Search active listings.

    * location / keyword: case-insensitive substring match
    * start & end: only cars available (and unbooked) for the whole window
    * max_price, car_type, min_seats: simple filters

    Values are passed separately from the SQL statement; only the sort clause
    comes from the fixed ``SORTS`` allowlist above.
    """
    sql = ("SELECT c.*, u.name AS owner_name, "
           " (SELECT ROUND(AVG(r.rating),1) FROM reviews r WHERE r.reviewee_id = c.owner_id) "
           "   AS avg_rating "
           "FROM cars c JOIN users u ON u.id = c.owner_id WHERE c.is_active = 1")
    params = []
    if location:
        sql += " AND LOWER(c.location) LIKE ?"
        params.append(f"%{location.lower().strip()}%")
    if keyword:
        sql += " AND LOWER(c.make || ' ' || c.model || ' ' || IFNULL(c.features,'')) LIKE ?"
        params.append(f"%{keyword.lower().strip()}%")
    if max_price:
        sql += " AND c.price_per_day <= ?"
        params.append(float(max_price))
    if car_type:
        sql += " AND c.car_type = ?"
        params.append(car_type)
    if min_seats:
        sql += " AND IFNULL(c.seats, 0) >= ?"
        params.append(int(min_seats))
    if exclude_owner:
        sql += " AND c.owner_id != ?"
        params.append(exclude_owner)
    sql += " ORDER BY " + SORTS.get(sort, SORTS["price_asc"])
    rows = db.execute(sql, params).fetchall()

    if start and end:
        s, e = bookings.normalize_window(start, end, allow_past=True)
        rows = [r for r in rows if bookings.is_available(db, r["id"], s, e)]
    return rows


def car_types(db):
    """Return the distinct non-empty car types available for filter controls."""
    return [r[0] for r in db.execute("SELECT DISTINCT car_type FROM cars WHERE car_type IS NOT NULL "
                                     "ORDER BY car_type").fetchall()]


def now_str():
    """Return the current local time in the format used by HTML date-time fields."""
    from datetime import datetime
    return datetime.now().strftime(TIME_FMT)

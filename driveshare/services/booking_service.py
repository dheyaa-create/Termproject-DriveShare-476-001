"""
booking_service.py
==================
Availability checks, pricing and the booking life-cycle.

Life-cycle of a booking::

    pending --(owner confirms)--> confirmed --(renter pays)--> paid
       |                              |
       +--(owner declines)--> declined
       +--(renter cancels)--> cancelled <--(renter cancels)--+

**No double booking.** ``create_booking`` opens a ``BEGIN IMMEDIATE``
transaction (an exclusive write lock in SQLite), re-checks for overlapping
active bookings and inserts the new booking in the same transaction, so two
renters clicking "Book" at the same moment cannot both succeed. A database
trigger (see ``database.py``) is a second safety net.

Two intervals [s1, e1) and [s2, e2) overlap exactly when ``s1 < e2 and s2 < e1``.
"""

import math
import sqlite3
from datetime import datetime

from driveshare.patterns.car_builder import TIME_FMT, parse_time
from driveshare.patterns.observer import CarEvent
from driveshare.services import notification_service as notes

ACTIVE_STATUSES = ("pending", "confirmed", "paid")


class BookingError(ValueError):
    """Raised when a rental window or booking lifecycle action is invalid."""

    pass


# --------------------------------------------------------------------------- #
# availability                                                                #
# --------------------------------------------------------------------------- #
def merged_windows(db, car_id):
    """Return a sorted union of the car's availability windows.

    Adjacent and overlapping windows are coalesced, allowing a rental to span
    multiple owner-entered windows when there is no gap between them.
    """
    rows = db.execute("SELECT start_time, end_time FROM car_availability "
                      "WHERE car_id = ? ORDER BY start_time", (car_id,)).fetchall()
    merged = []
    for r in rows:
        if merged and r["start_time"] <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], r["end_time"])
        else:
            merged.append([r["start_time"], r["end_time"]])
    return merged


def within_availability(db, car_id, start, end):
    """Return whether the requested half-open interval fits an offered window."""
    return any(ws <= start and end <= we for ws, we in merged_windows(db, car_id))


def conflicting_bookings(db, car_id, start, end, exclude_id=None):
    """Find active reservations that intersect the requested interval.

    The strict comparisons implement half-open intervals: back-to-back
    bookings are allowed, while any shared rental time is considered overlap.
    ``exclude_id`` supports checking an existing booking during an update.
    """
    sql = ("SELECT * FROM bookings WHERE car_id = ? AND status IN ('pending','confirmed','paid') "
           "AND start_time < ? AND end_time > ?")
    params = [car_id, end, start]
    if exclude_id:
        sql += " AND id != ?"
        params.append(exclude_id)
    return db.execute(sql, params).fetchall()


def is_available(db, car_id, start, end):
    """Require both owner availability and no overlapping active reservation."""
    return within_availability(db, car_id, start, end) and not conflicting_bookings(db, car_id, start, end)


def normalize_window(start, end, allow_past=False):
    """Validate a rental interval and return normalized ISO date-time strings.

    Past pickups are rejected for new bookings. Search may opt into past dates
    so historical or demo data can still be queried.
    """
    s, e = parse_time(start), parse_time(end)
    if e <= s:
        raise BookingError("Drop-off must be after pick-up.")
    if not allow_past and s < datetime.now().replace(second=0, microsecond=0):
        raise BookingError("Pick-up time cannot be in the past.")
    return s.strftime(TIME_FMT), e.strftime(TIME_FMT)


def rental_days(start, end):
    """Calculate billable rental days, rounding every started day upward."""
    hours = (parse_time(end) - parse_time(start)).total_seconds() / 3600
    return max(1, math.ceil(hours / 24))


def quote(price_per_day, start, end):
    """Return the billable day count and rounded total for a rental interval."""
    days = rental_days(start, end)
    return days, round(days * price_per_day, 2)


# --------------------------------------------------------------------------- #
# life-cycle                                                                  #
# --------------------------------------------------------------------------- #
def create_booking(db, car_id, renter_id, start, end):
    """Atomically validate a rental and create its initial pending reservation.

    The write lock is acquired before the final availability check. This
    prevents two concurrent renters from both passing the check for the same
    time window; a database trigger independently guards the insert.
    """
    start, end = normalize_window(start, end)
    car = db.execute("SELECT * FROM cars WHERE id = ? AND is_active = 1", (car_id,)).fetchone()
    if car is None:
        raise BookingError("This car is not available for booking.")
    if car["owner_id"] == renter_id:
        raise BookingError("You cannot book your own car.")

    if db.in_transaction:
        db.commit()
    db.execute("BEGIN IMMEDIATE")          # exclusive write lock -> no race
    try:
        if not within_availability(db, car_id, start, end):
            raise BookingError("The owner has not made the car available for that whole period.")
        if conflicting_bookings(db, car_id, start, end):
            raise BookingError("Sorry - the car is already booked for part of that period.")
        days, total = quote(car["price_per_day"], start, end)
        cur = db.execute("INSERT INTO bookings (car_id, renter_id, start_time, end_time, total_price) "
                         "VALUES (?, ?, ?, ?, ?)", (car_id, renter_id, start, end, total))
        booking_id = cur.lastrowid
        db.commit()
    except sqlite3.IntegrityError as exc:  # trigger fired (should never happen)
        db.rollback()
        raise BookingError(str(exc))
    except Exception:
        db.rollback()
        raise

    title = f"{car['year']} {car['make']} {car['model']}"
    renter = db.execute("SELECT name FROM users WHERE id = ?", (renter_id,)).fetchone()
    notes.notify(db, car["owner_id"], "booking",
                 f"New booking request from {renter['name']} for your {title} "
                 f"({start.replace('T', ' ')} - {end.replace('T', ' ')}, ${total:.2f}).",
                 "/bookings")
    notes.notify(db, renter_id, "booking",
                 f"Your request for the {title} was sent to the owner. "
                 f"You will be notified when it is confirmed.", "/bookings")
    return booking_id


def get_booking(db, booking_id):
    """Load a booking together with car, owner, and renter display details."""
    return db.execute(
        "SELECT b.*, c.make, c.model, c.year, c.owner_id, c.location, c.price_per_day, "
        "o.name AS owner_name, r.name AS renter_name "
        "FROM bookings b JOIN cars c ON c.id = b.car_id "
        "JOIN users o ON o.id = c.owner_id JOIN users r ON r.id = b.renter_id "
        "WHERE b.id = ?", (booking_id,)).fetchone()


def _title(b):
    """Build the consistent year/make/model label used in notifications."""
    return f"{b['year']} {b['make']} {b['model']}"


def respond(db, booking_id, owner_id, accept, publisher=None):
    """Let the car owner confirm or decline a pending booking.

    Declining releases the reserved dates; when supplied, the event publisher
    re-evaluates watches that may now match those dates.
    """
    b = get_booking(db, booking_id)
    if b is None or b["owner_id"] != owner_id:
        raise BookingError("Booking not found.")
    if b["status"] != "pending":
        raise BookingError("Only pending bookings can be confirmed or declined.")
    status = "confirmed" if accept else "declined"
    db.execute("UPDATE bookings SET status = ? WHERE id = ?", (status, booking_id))
    db.commit()
    if accept:
        notes.notify(db, b["renter_id"], "booking",
                     f"Booking confirmed! {b['owner_name']} accepted your request for the "
                     f"{_title(b)}. Please complete payment of ${b['total_price']:.2f}.",
                     "/bookings")
    else:
        notes.notify(db, b["renter_id"], "booking",
                     f"Your request for the {_title(b)} was declined by the owner.", "/bookings")
        if publisher:                      # dates are free again -> tell watchers
            publisher.publish(b["car_id"], CarEvent.BOOKING_RELEASED)


def cancel(db, booking_id, renter_id, publisher=None):
    """Allow the renter to cancel a pending or confirmed unpaid booking."""
    b = get_booking(db, booking_id)
    if b is None or b["renter_id"] != renter_id:
        raise BookingError("Booking not found.")
    if b["status"] not in ("pending", "confirmed"):
        raise BookingError("This booking can no longer be cancelled.")
    db.execute("UPDATE bookings SET status = 'cancelled' WHERE id = ?", (booking_id,))
    db.commit()
    notes.notify(db, b["owner_id"], "booking",
                 f"{b['renter_name']} cancelled their booking of your {_title(b)}.", "/bookings")
    if publisher:
        publisher.publish(b["car_id"], CarEvent.BOOKING_RELEASED)


def display_status(b):
    """Present elapsed paid rentals as completed without changing stored state."""
    if b["status"] == "paid" and b["end_time"] < datetime.now().strftime(TIME_FMT):
        return "completed"
    return b["status"]


def bookings_as_renter(db, user_id):
    """List a user's rentals as renter, with the corresponding owner names."""
    return db.execute(
        "SELECT b.*, c.make, c.model, c.year, c.owner_id, o.name AS owner_name "
        "FROM bookings b JOIN cars c ON c.id = b.car_id JOIN users o ON o.id = c.owner_id "
        "WHERE b.renter_id = ? ORDER BY b.start_time DESC", (user_id,)).fetchall()


def bookings_as_owner(db, user_id):
    """List reservations for the user's cars, with renter display names."""
    return db.execute(
        "SELECT b.*, c.make, c.model, c.year, c.owner_id, r.name AS renter_name "
        "FROM bookings b JOIN cars c ON c.id = b.car_id JOIN users r ON r.id = b.renter_id "
        "WHERE c.owner_id = ? ORDER BY b.start_time DESC", (user_id,)).fetchall()

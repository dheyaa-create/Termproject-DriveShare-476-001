"""
database.py
===========
SQLite persistence layer for DriveShare.

This module owns the database schema and hands out connections. Every other
module talks to the database through ``get_db()`` so there is exactly one
place that knows the file location and connection settings.

Tables (see docs/REPORT.md for the full ER diagram):
    users              - account, hashed password, simulated wallet balance
    security_questions - the three recovery questions per user (answers hashed)
    cars               - a car listing built by CarListingBuilder
    car_availability   - date/time windows in which an owner offers a car
    bookings           - a renter's reservation of a car for a time window
    payments           - simulated payments processed through PaymentProxy
    watches            - renter "watch" criteria used by the Observer pattern
    notifications      - in-app notifications (also mirrored to email outbox)
    messages           - owner <-> renter direct messages
    reviews            - ratings left by owner and renter after a rental
"""

import os
import sqlite3

from flask import g, current_app

# --------------------------------------------------------------------------- #
# Schema                                                                      #
# --------------------------------------------------------------------------- #
SCHEMA = """
PRAGMA foreign_keys = ON;

-- A user owns cars and holds a simulated wallet balance. Passwords are stored
-- only as hashes; failed_recovery tracks recovery attempts for lockout.
CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    email           TEXT    NOT NULL UNIQUE,
    name            TEXT    NOT NULL,
    password_hash   TEXT    NOT NULL,
    balance         REAL    NOT NULL DEFAULT 1000.0,   -- simulated wallet
    failed_recovery INTEGER NOT NULL DEFAULT 0,        -- recovery lockout counter
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- One row per recovery question. Position keeps the three answers in a
-- stable order, while the unique constraint prevents duplicate positions.
CREATE TABLE IF NOT EXISTS security_questions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    position    INTEGER NOT NULL CHECK (position BETWEEN 1 AND 3),
    question    TEXT    NOT NULL,
    answer_hash TEXT    NOT NULL,
    UNIQUE (user_id, position)
);

-- Listing details belong to an owner. Optional vehicle details may be NULL;
-- is_active hides a listing without deleting its related history.
CREATE TABLE IF NOT EXISTS cars (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    make          TEXT    NOT NULL,
    model         TEXT    NOT NULL,
    year          INTEGER NOT NULL,
    mileage       INTEGER NOT NULL,
    location      TEXT    NOT NULL,
    price_per_day REAL    NOT NULL,
    car_type      TEXT,                 -- optional (Sedan, SUV, ...)
    seats         INTEGER,              -- optional
    transmission  TEXT,                 -- optional
    fuel_type     TEXT,                 -- optional
    features      TEXT,                 -- optional, comma separated
    description   TEXT,                 -- optional
    is_active     INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Availability is represented as half-open time windows [start_time, end_time).
-- The CHECK prevents empty or reversed windows.
CREATE TABLE IF NOT EXISTS car_availability (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    car_id     INTEGER NOT NULL REFERENCES cars(id) ON DELETE CASCADE,
    start_time TEXT    NOT NULL,        -- ISO 8601 'YYYY-MM-DDTHH:MM'
    end_time   TEXT    NOT NULL,
    CHECK (end_time > start_time)
);

-- A booking reserves a car for one renter and progresses through the
-- lifecycle documented in booking_service.py.
CREATE TABLE IF NOT EXISTS bookings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    car_id      INTEGER NOT NULL REFERENCES cars(id) ON DELETE CASCADE,
    renter_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    start_time  TEXT    NOT NULL,
    end_time    TEXT    NOT NULL,
    total_price REAL    NOT NULL,
    -- pending -> confirmed -> paid ; or declined / cancelled
    status      TEXT    NOT NULL DEFAULT 'pending',
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    CHECK (end_time > start_time)
);

-- Successful simulated payments are unique per booking, preventing a second
-- payment record from being attached to the same reservation.
CREATE TABLE IF NOT EXISTS payments (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    booking_id INTEGER NOT NULL UNIQUE REFERENCES bookings(id) ON DELETE CASCADE,
    payer_id   INTEGER NOT NULL REFERENCES users(id),
    payee_id   INTEGER NOT NULL REFERENCES users(id),
    amount     REAL    NOT NULL,
    reference  TEXT    NOT NULL,        -- simulated transaction id
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Each renter can keep one watch per car. Either a price threshold, a date
-- window, or both may be used to decide when to send a notification.
CREATE TABLE IF NOT EXISTS watches (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    renter_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    car_id       INTEGER NOT NULL REFERENCES cars(id) ON DELETE CASCADE,
    max_price    REAL,                  -- notify when price_per_day <= max_price
    start_time   TEXT,                  -- notify when available for this window
    end_time     TEXT,
    active       INTEGER NOT NULL DEFAULT 1,
    last_notified TEXT,
    created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (renter_id, car_id)
);

-- In-app messages shown in the notification center. The optional link lets
-- the interface direct the user to the related booking, car, or conversation.
CREATE TABLE IF NOT EXISTS notifications (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind       TEXT    NOT NULL,        -- booking / payment / watch / message / review
    message    TEXT    NOT NULL,
    link       TEXT,
    is_read    INTEGER NOT NULL DEFAULT 0,
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Direct messages are stored as sender/recipient pairs. If a related car is
-- removed, SET NULL preserves the conversation rather than deleting it.
CREATE TABLE IF NOT EXISTS messages (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    sender_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    recipient_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    car_id       INTEGER REFERENCES cars(id) ON DELETE SET NULL,
    body         TEXT    NOT NULL,
    is_read      INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Reviews are tied to a rental and reviewer. The unique key permits each
-- participant to submit at most one review for that booking.
CREATE TABLE IF NOT EXISTS reviews (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    booking_id  INTEGER NOT NULL REFERENCES bookings(id) ON DELETE CASCADE,
    reviewer_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    reviewee_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    rating      INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    comment     TEXT,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (booking_id, reviewer_id)   -- one review per side per booking
);

-- Defence in depth for "no double booking": even if application code had a
-- bug, the database itself refuses an overlapping active booking.
CREATE TRIGGER IF NOT EXISTS prevent_double_booking
BEFORE INSERT ON bookings
WHEN EXISTS (
    SELECT 1 FROM bookings
    WHERE car_id = NEW.car_id
      AND status IN ('pending', 'confirmed', 'paid')
      AND start_time < NEW.end_time
      AND end_time   > NEW.start_time
)
BEGIN
    SELECT RAISE(ABORT, 'Car is already booked for an overlapping period');
END;

-- Indexes support the common lookup paths used by booking checks, availability
-- queries, notification badges, and Observer watch publication.
CREATE INDEX IF NOT EXISTS idx_bookings_car  ON bookings(car_id, start_time, end_time);
CREATE INDEX IF NOT EXISTS idx_avail_car     ON car_availability(car_id);
CREATE INDEX IF NOT EXISTS idx_notif_user    ON notifications(user_id, is_read);
CREATE INDEX IF NOT EXISTS idx_watch_car     ON watches(car_id, active);
"""


def _connect(path):
    """Open a SQLite connection with the settings used throughout the app.

    ``sqlite3.Row`` allows services and templates to access query results by
    column name. Foreign-key enforcement is enabled per connection because
    SQLite does not enable it globally by default.
    """
    conn = sqlite3.connect(path, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_db():
    """
    Return the connection bound to the current Flask request (``g``).

    A new connection is created lazily the first time it is needed in a
    request and closed automatically by ``close_db`` at teardown.
    """
    if "db" not in g:
        g.db = _connect(current_app.config["DATABASE"])
    return g.db


def close_db(_exc=None):
    """Flask teardown hook that releases the lazy request-scoped connection.

    Flask may call this hook even when a request never needed the database, so
    the connection is removed from ``g`` and closed only when it exists.
    """
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(path):
    """Ensure the database directory and complete schema exist.

    Schema statements use ``IF NOT EXISTS``, making initialization safe to run
    at every application startup without replacing existing user data.
    """
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = _connect(path)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


def init_app(app):
    """Attach database lifecycle handling and initialize this app's database.

    The application factory calls this once for each Flask app instance. The
    configured database path isolates test databases from the normal database.
    """
    app.teardown_appcontext(close_db)
    init_db(app.config["DATABASE"])

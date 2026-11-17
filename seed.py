"""
seed.py - reset the database and load demo data for the presentation.

Creates three users (password for all: ``Password123``):

    alice@driveshare.test   owner of three cars
    bob@driveshare.test     renter
    carol@driveshare.test   owner of two cars and occasional renter

Security answers for every demo user: ``blue``, ``ann arbor``, ``smith``.
It also creates one completed (paid, past) rental with reviews so the
history and review features have something to show.
"""

import os
import sqlite3
from datetime import datetime, timedelta

from driveshare import create_app
from driveshare.database import get_db
from driveshare.patterns.car_builder import CarListingBuilder, CarListingDirector
from driveshare.services import auth_service, car_service

QUESTIONS = ["What is your favorite color?", "In what city were you born?",
             "What is your mother's maiden name?"]
ANSWERS = ["blue", "ann arbor", "smith"]
FMT = "%Y-%m-%dT%H:%M"


def day(offset, hour=9):
    """Format a local date-time a number of days from now for demo records."""
    d = datetime.now().replace(hour=hour, minute=0, second=0, microsecond=0) + timedelta(days=offset)
    return d.strftime(FMT)


def main():
    """Reset the configured demo database and insert reproducible sample data.

    This script intentionally removes the existing database and simulated
    email outbox before rebuilding them; run it only when demo data is desired.
    """
    app = create_app()
    db_path = app.config["DATABASE"]
    for path in (db_path, app.config["EMAIL_OUTBOX"]):
        if os.path.exists(path):
            os.remove(path)
    app = create_app()                      # recreate schema
    with app.app_context():
        db = get_db()
        uid = {}
        for name, email in [("Alice Johnson", "alice@driveshare.test"),
                            ("Bob Smith", "bob@driveshare.test"),
                            ("Carol Lee", "carol@driveshare.test")]:
            uid[email.split("@")[0]] = auth_service.register_user(
                db, name, email, "Password123", QUESTIONS, ANSWERS)

        # --- listings: two via the Director, the rest via the fluent Builder ---
        cars = {}
        cars["camry"] = car_service.save_listing(db, CarListingDirector.economy_sedan(
            CarListingBuilder(uid["alice"]), "Toyota", "Camry", 2021, "Ann Arbor, MI", 55)
            .set_description("Clean, reliable and great on gas. Perfect for weekend trips.")
            .add_availability(day(-20), day(60, 20)).build())
        cars["rav4"] = car_service.save_listing(db, CarListingDirector.family_suv(
            CarListingBuilder(uid["alice"]), "Toyota", "RAV4 Hybrid", 2023, "Ann Arbor, MI", 89)
            .add_availability(day(1), day(45, 20)).build())
        cars["model3"] = car_service.save_listing(db, (
            CarListingBuilder(uid["alice"]).set_model("Tesla", "Model 3").set_year(2022)
            .set_mileage(18000).set_location("Detroit, MI").set_price_per_day(120)
            .set_car_type("Electric").set_seats(5).set_transmission("Automatic")
            .set_fuel_type("Electric").set_features("Autopilot, Supercharger access, Glass roof")
            .set_description("Zero emissions and a lot of fun.")
            .add_availability(day(3), day(10, 20)).add_availability(day(20), day(40, 20)).build()))
        cars["civic"] = car_service.save_listing(db, (
            CarListingBuilder(uid["carol"]).set_model("Honda", "Civic").set_year(2019)
            .set_mileage(41000).set_location("Ypsilanti, MI").set_price_per_day(42)
            .set_car_type("Sedan").set_seats(5).set_transmission("Manual")
            .set_features("Bluetooth, Apple CarPlay").add_availability(day(0, 8), day(30, 20)).build()))
        cars["f150"] = car_service.save_listing(db, (
            CarListingBuilder(uid["carol"]).set_model("Ford", "F-150").set_year(2020)
            .set_mileage(52000).set_location("Dearborn, MI").set_price_per_day(95)
            .set_car_type("Truck").set_seats(5).set_transmission("Automatic").set_fuel_type("Gasoline")
            .set_features("Tow hitch, 4x4").add_availability(day(2), day(50, 20)).build()))

        # --- a finished rental (Bob rented Alice's Camry last week) + reviews ---
        db.execute("INSERT INTO bookings (car_id, renter_id, start_time, end_time, total_price, status) "
                   "VALUES (?, ?, ?, ?, ?, 'paid')", (cars["camry"], uid["bob"], day(-10), day(-7), 165))
        bid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute("INSERT INTO payments (booking_id, payer_id, payee_id, amount, reference) "
                   "VALUES (?, ?, ?, 165, 'DS-SEED00001')", (bid, uid["bob"], uid["alice"]))
        db.execute("UPDATE users SET balance = balance - 165 WHERE id = ?", (uid["bob"],))
        db.execute("UPDATE users SET balance = balance + 165 WHERE id = ?", (uid["alice"],))
        db.execute("INSERT INTO reviews (booking_id, reviewer_id, reviewee_id, rating, comment) VALUES "
                   "(?, ?, ?, 5, 'Alice was super responsive and the car was spotless.')",
                   (bid, uid["bob"], uid["alice"]))
        db.execute("INSERT INTO reviews (booking_id, reviewer_id, reviewee_id, rating, comment) VALUES "
                   "(?, ?, ?, 5, 'Bob returned the car on time and full of gas. Great renter!')",
                   (bid, uid["alice"], uid["bob"]))
        db.execute("INSERT INTO messages (sender_id, recipient_id, car_id, body) VALUES "
                   "(?, ?, ?, 'Hi Alice! Is the Camry OK for a trip to Chicago?')",
                   (uid["bob"], uid["alice"], cars["camry"]))
        db.execute("INSERT INTO messages (sender_id, recipient_id, car_id, body) VALUES "
                   "(?, ?, ?, 'Absolutely - unlimited miles. Enjoy!')",
                   (uid["alice"], uid["bob"], cars["camry"]))
        db.commit()
    print("Demo data loaded. Log in as alice@ / bob@ / carol@driveshare.test with password Password123")


if __name__ == "__main__":
    main()

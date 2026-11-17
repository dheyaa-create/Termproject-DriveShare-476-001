"""Shared pytest fixtures: a fresh app + database per test."""
import os
import sys
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from driveshare import create_app                      # noqa: E402
from driveshare.database import get_db                 # noqa: E402
from driveshare.patterns.car_builder import CarListingBuilder  # noqa: E402
from driveshare.services import auth_service, car_service      # noqa: E402

QS = ["Q one?", "Q two?", "Q three?"]
AS = ["red", "paris", "rex"]


def t(days, hour=10):
    """ISO time ``days`` from now at ``hour``:00."""
    return (datetime.now().replace(hour=hour, minute=0, second=0, microsecond=0)
            + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M")


@pytest.fixture
def app(tmp_path):
    """Create an isolated app with owner, renters, and one available car."""
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "test.db"),
                      "EMAIL_OUTBOX": str(tmp_path / "outbox.log")})
    with app.app_context():
        db = get_db()
        owner = auth_service.register_user(db, "Owner", "owner@x.com", "Password1", QS, AS)
        renter = auth_service.register_user(db, "Renter", "renter@x.com", "Password1", QS, AS)
        renter2 = auth_service.register_user(db, "Renter Two", "renter2@x.com", "Password1", QS, AS)
        car = car_service.save_listing(db, CarListingBuilder(owner).set_model("Honda", "Fit")
                                       .set_year(2020).set_mileage(1000).set_location("Ann Arbor")
                                       .set_price_per_day(50).add_availability(t(1), t(30)).build())
    app.ids = {"owner": owner, "renter": renter, "renter2": renter2, "car": car}
    return app


@pytest.fixture
def ctx(app):
    """Provide the test app's database connection inside its app context."""
    with app.app_context():
        yield get_db()


def login(client, email):
    """Authenticate a test client using the shared fixture password."""
    return client.post("/login", data={"email": email, "password": "Password1"})

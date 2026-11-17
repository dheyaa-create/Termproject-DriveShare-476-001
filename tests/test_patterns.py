"""Unit tests - one group per design pattern plus the double-booking rule."""
import os
import sqlite3

import pytest

from conftest import AS, login, t
from driveshare.patterns.car_builder import (CarListingBuilder, CarListingDirector,
                                             ListingValidationError)
from driveshare.patterns.observer import CarListingSubject, WatchObserver
from driveshare.patterns.password_recovery import RecoveryRequest, build_recovery_chain
from driveshare.patterns.payment_proxy import PaymentProxy, PaymentRequest
from driveshare.patterns.session_manager import SessionManager
from driveshare.security import normalize_answer, password_problem
from driveshare.services import booking_service as bookings
from driveshare.services import car_service, community_service as community
from driveshare.services import notification_service


# ----------------------------- Singleton ----------------------------- #
def test_session_manager_is_singleton():
    """Repeated construction returns the same process-wide manager."""
    assert SessionManager() is SessionManager()


def test_session_lifecycle():
    """Sessions resolve, store only token hashes, and can be revoked."""
    sm = SessionManager()
    tok = sm.create_session(42)
    assert sm.get_user_id(tok) == 42
    assert tok not in sm._sessions            # only hashes are stored
    sm.end_session(tok)
    assert sm.get_user_id(tok) is None


# ------------------------------ Builder ------------------------------ #
def test_builder_requires_fields():
    """Building an incomplete listing reports missing required attributes."""
    with pytest.raises(ListingValidationError):
        CarListingBuilder(1).set_model("A", "B").build()


def test_builder_optional_and_director():
    """A Director recipe populates optional fields and a readable title."""
    car = CarListingDirector.family_suv(CarListingBuilder(1), "Kia", "Telluride", 2023, "Detroit", 99).build()
    assert car.seats == 7 and "AWD" in car.features and car.title == "2023 Kia Telluride"


def test_builder_rejects_bad_window():
    """Availability windows must end after their start."""
    with pytest.raises(ListingValidationError):
        CarListingBuilder(1).add_availability(t(5), t(2))


# ------------------------------ Observer ----------------------------- #
def test_observer_price_drop():
    """A watch stays silent above its target and notifies once it qualifies."""
    sent = []
    car = {"id": 1, "make": "A", "model": "B", "year": 2020, "price_per_day": 80}
    subject = CarListingSubject(car)
    obs = WatchObserver({"renter_id": 7, "max_price": 60}, lambda *a: True,
                        lambda *a: sent.append(a))
    subject.attach(obs)
    subject.notify_observers("price_changed")
    assert not sent                               # 80 > 60 -> silent
    car["price_per_day"] = 55
    subject.notify_observers("price_changed")
    assert sent and sent[0][0] == 7


def test_watch_notified_on_price_update(app, ctx):
    """Persisted price changes publish events to matching active watches."""
    ids = app.ids
    community.add_watch(ctx, ids["renter"], ids["car"], max_price=40)
    before = ctx.execute("SELECT COUNT(*) FROM notifications WHERE user_id=? AND kind='watch'",
                         (ids["renter"],)).fetchone()[0]
    assert before == 0
    car_service.update_price(ctx, ids["car"], ids["owner"], 39)
    after = ctx.execute("SELECT COUNT(*) FROM notifications WHERE user_id=? AND kind='watch'",
                        (ids["renter"],)).fetchone()[0]
    assert after == 1


def test_watch_notified_when_booking_released(app, ctx):
    """Cancelling a reservation re-evaluates watches for the newly free dates."""
    ids = app.ids
    b = bookings.create_booking(ctx, ids["car"], ids["renter"], t(2), t(4))
    community.add_watch(ctx, ids["renter2"], ids["car"], start=t(3), end=t(5))
    count = lambda: ctx.execute("SELECT COUNT(*) FROM notifications WHERE user_id=? AND kind='watch'",
                                (ids["renter2"],)).fetchone()[0]
    assert count() == 0
    bookings.cancel(ctx, b, ids["renter"], car_service.make_publisher(ctx))
    assert count() == 1


# ------------------------- No double booking ------------------------- #
def test_overlapping_booking_rejected(app, ctx):
    """Overlapping reservations fail while adjacent reservations are permitted."""
    ids = app.ids
    bookings.create_booking(ctx, ids["car"], ids["renter"], t(2), t(5))
    with pytest.raises(bookings.BookingError):
        bookings.create_booking(ctx, ids["car"], ids["renter2"], t(4), t(6))
    # back-to-back is fine
    bookings.create_booking(ctx, ids["car"], ids["renter2"], t(5), t(7))


def test_db_trigger_blocks_overlap(app, ctx):
    """The database trigger independently blocks a conflicting direct insert."""
    ids = app.ids
    bookings.create_booking(ctx, ids["car"], ids["renter"], t(2), t(5))
    with pytest.raises(sqlite3.IntegrityError):
        ctx.execute("INSERT INTO bookings (car_id, renter_id, start_time, end_time, total_price) "
                    "VALUES (?,?,?,?,1)", (ids["car"], ids["renter2"], t(3), t(4)))


def test_booking_outside_availability_rejected(app, ctx):
    """A booking cannot extend beyond the owner's offered availability."""
    with pytest.raises(bookings.BookingError):
        bookings.create_booking(ctx, app.ids["car"], app.ids["renter"], t(29), t(32))


def test_price_is_per_started_day(app, ctx):
    """Any partial extra 24-hour period is billed as a complete day."""
    assert bookings.quote(50, t(1, 10), t(3, 12)) == (3, 150)


# ------------------------------- Proxy ------------------------------- #
def test_proxy_blocks_unconfirmed_and_wrong_user(app, ctx):
    """The payment proxy validates booking state, payer, amount, and repeats."""
    ids = app.ids
    b = bookings.create_booking(ctx, ids["car"], ids["renter"], t(2), t(4))
    proxy = PaymentProxy(ctx)
    assert not proxy.process_payment(PaymentRequest(b, ids["renter"], 100)).success  # pending
    bookings.respond(ctx, b, ids["owner"], True)
    assert not proxy.process_payment(PaymentRequest(b, ids["renter2"], 100)).success  # wrong user
    assert not proxy.process_payment(PaymentRequest(b, ids["renter"], 1)).success     # wrong amount
    assert proxy._real_gateway is None              # real gateway never created (lazy)
    res = proxy.process_payment(PaymentRequest(b, ids["renter"], 100))
    assert res.success
    bal = {r["id"]: r["balance"] for r in ctx.execute("SELECT id, balance FROM users")}
    assert bal[ids["renter"]] == 900 and bal[ids["owner"]] == 1100
    assert not proxy.process_payment(PaymentRequest(b, ids["renter"], 100)).success   # paid twice


# ----------------------- Chain of Responsibility --------------------- #
def test_recovery_chain(app, ctx):
    """Recovery handlers run in order and stop at the first incorrect answer."""
    uid = app.ids["renter"]
    chain = build_recovery_chain(ctx)
    bad = chain.handle(RecoveryRequest(uid, ["red", "WRONG", "rex"], "NewPass99"))
    assert not bad.success and bad.failed_at == "question_2"
    req = RecoveryRequest(uid, ["  RED ", "Paris", "rex"], "NewPass99")
    ok = build_recovery_chain(ctx).handle(req)
    assert ok.success and req.passed == ["lockout", "question_1", "question_2", "question_3", "reset"]


def test_recovery_lockout(app, ctx):
    """Five failed recovery attempts prevent another security-question attempt."""
    uid = app.ids["renter"]
    for _ in range(5):
        build_recovery_chain(ctx).handle(RecoveryRequest(uid, ["x", "x", "x"], "NewPass99"))
    res = build_recovery_chain(ctx).handle(RecoveryRequest(uid, AS, "NewPass99"))
    assert not res.success and res.failed_at == "lockout"


# ------------------------- end-to-end (HTTP) ------------------------- #
def test_full_rental_flow(app):
    """Exercise booking, confirmation, payment, reviews, messages, and notices."""
    ids = app.ids
    owner, renter = app.test_client(), app.test_client()
    login(owner, "owner@x.com"); login(renter, "renter@x.com")
    r = renter.post(f"/cars/{ids['car']}/book", data={"start": t(2), "end": t(4)})
    assert r.status_code == 302
    owner.post("/bookings/1/confirm")
    renter.post("/bookings/1/pay", data={"amount": "100.00"})
    renter.post("/bookings/1/review", data={"rating": 5, "comment": "great"})
    owner.post("/bookings/1/review", data={"rating": 4, "tab": "owner"})
    page = renter.get("/bookings").get_data(as_text=True)
    assert "paid" in page and "Reviewed" in page
    renter.post(f"/messages/{ids['owner']}", data={"body": "Thanks!"})
    assert "Thanks!" in owner.get(f"/messages/{ids['renter']}").get_data(as_text=True)
    notes = owner.get("/notifications").get_data(as_text=True)
    assert "New booking request" in notes and "You received $100.00" in notes


def test_register_and_recover_via_http(app):
    """Register through HTTP, recover the password, and log in with the reset."""
    c = app.test_client()
    data = {"name": "New", "email": "new@x.com", "password": "Secret123", "confirm": "Secret123",
            "question1": "A?", "question2": "B?", "question3": "C?",
            "answer1": "1", "answer2": "2", "answer3": "3"}
    assert c.post("/register", data=data).status_code == 302
    c.get("/logout")
    c.post("/recover", data={"email": "new@x.com"})
    r = c.post("/recover/verify", data={"answer1": "1", "answer2": "2", "answer3": "3",
                                        "password": "Brand9new", "confirm": "Brand9new"})
    assert r.status_code == 302
    assert c.post("/login", data={"email": "new@x.com", "password": "Brand9new"}).status_code == 302


def test_security_helpers_handle_non_string_inputs():
    """Security utilities normalize non-string values and enforce the policy."""
    assert normalize_answer(123) == "123"
    assert password_problem(1234567) == "Password must be at least 8 characters."
    assert password_problem("Password123") is None


def test_notification_email_outbox_allows_relative_path(app, tmp_path):
    """A relative outbox filename is created in the current working directory."""
    app.config["EMAIL_OUTBOX"] = "outbox.log"
    cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        with app.app_context():
            from driveshare.database import get_db
            db = get_db()
            notification_service.notify(db, app.ids["renter"], "test", "hello")
        assert (tmp_path / "outbox.log").exists()
    finally:
        os.chdir(cwd)

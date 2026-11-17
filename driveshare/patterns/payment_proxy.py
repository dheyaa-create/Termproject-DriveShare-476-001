"""
payment_proxy.py  -  PROXY PATTERN
=================================

Problem
-------
DriveShare must never talk to a payment processor directly from a button
click: the request must first be authenticated, authorised, validated and
audited. Putting those checks inside the payment processor would mix
security concerns with money movement; putting them in every caller would
duplicate them.

Solution
--------
* ``PaymentGateway`` - the common *Subject* interface (``process_payment``).
* ``SimulatedPaymentGateway`` - the *Real Subject*. It moves money between
  the renter's and the owner's simulated wallets and records the payment.
  (No real card network is used - this satisfies the project requirement.)
* ``PaymentProxy`` - the *Proxy*. It exposes the same interface, so callers
  cannot tell it apart from the real gateway, but before delegating it:
    1. checks the caller is logged in (authentication),
    2. checks the caller is the renter on the booking (authorisation),
    3. checks the booking is confirmed and not already paid (idempotency),
    4. checks the amount equals the booking total (tamper protection),
    5. checks the renter has enough balance,
    6. writes an audit log line with the card number masked,
  and it creates the real gateway lazily (virtual-proxy behaviour) only when a
  payment actually passes all checks.
"""

import logging
import secrets
from abc import ABC, abstractmethod
from dataclasses import dataclass

audit_log = logging.getLogger("driveshare.payments")


@dataclass
class PaymentRequest:
    """Payment input; ``payer_id`` comes from the authenticated application user."""

    booking_id: int
    payer_id: int            # the user clicking "Pay" (from SessionManager)
    amount: float
    card_last4: str = "4242"  # simulated card - only last 4 digits ever kept


@dataclass
class PaymentResult:
    """Structured payment outcome returned by both proxy and gateway."""

    success: bool
    message: str
    reference: str = ""
    amount: float = 0.0
    payer_id: int = 0
    payee_id: int = 0


class PaymentError(Exception):
    """Raised by the proxy when a request is rejected."""


class PaymentGateway(ABC):
    """Common interface shared by the real gateway and its proxy."""

    @abstractmethod
    def process_payment(self, request: PaymentRequest) -> PaymentResult:
        """Process a payment request and return its result."""
        ...


class SimulatedPaymentGateway(PaymentGateway):
    """Real subject: performs the (simulated) money transfer atomically."""

    def __init__(self, db):
        """Retain the connection used for the atomic wallet and booking updates."""
        self.db = db

    def process_payment(self, request):
        """Move the simulated funds and persist the payment as one transaction.

        Any database error rolls back all balance, payment, and booking-status
        changes before it is re-raised to the caller.
        """
        db = self.db
        booking = db.execute(
            "SELECT b.*, c.owner_id FROM bookings b JOIN cars c ON c.id = b.car_id "
            "WHERE b.id = ?", (request.booking_id,)).fetchone()
        reference = "DS-" + secrets.token_hex(6).upper()
        try:
            # One transaction: debit, credit, record, mark paid - all or nothing.
            db.execute("UPDATE users SET balance = balance - ? WHERE id = ?",
                       (request.amount, request.payer_id))
            db.execute("UPDATE users SET balance = balance + ? WHERE id = ?",
                       (request.amount, booking["owner_id"]))
            db.execute("INSERT INTO payments (booking_id, payer_id, payee_id, amount, reference) "
                       "VALUES (?, ?, ?, ?, ?)",
                       (booking["id"], request.payer_id, booking["owner_id"],
                        request.amount, reference))
            db.execute("UPDATE bookings SET status = 'paid' WHERE id = ?", (booking["id"],))
            db.commit()
        except Exception:
            db.rollback()
            raise
        return PaymentResult(True, "Payment processed.", reference, request.amount,
                             request.payer_id, booking["owner_id"])


class PaymentProxy(PaymentGateway):
    """Protection + virtual proxy in front of ``SimulatedPaymentGateway``."""

    def __init__(self, db, gateway_factory=SimulatedPaymentGateway):
        """Create a validating proxy without constructing its gateway yet."""
        self.db = db
        self._gateway_factory = gateway_factory
        self._real_gateway = None           # created lazily

    def _gateway(self):
        """Lazily construct and then reuse the wrapped payment gateway."""
        if self._real_gateway is None:
            self._real_gateway = self._gateway_factory(self.db)
        return self._real_gateway

    def _validate(self, request):
        """Raise ``PaymentError`` unless identity, state, amount, and funds are valid."""
        if not request.payer_id:
            raise PaymentError("You must be logged in to pay.")
        booking = self.db.execute("SELECT * FROM bookings WHERE id = ?",
                                  (request.booking_id,)).fetchone()
        if booking is None:
            raise PaymentError("Booking not found.")
        if booking["renter_id"] != request.payer_id:
            raise PaymentError("Only the renter of this booking can pay for it.")
        if booking["status"] == "paid":
            raise PaymentError("This booking has already been paid.")
        if booking["status"] != "confirmed":
            raise PaymentError("The owner must confirm the booking before payment.")
        if round(float(request.amount), 2) != round(booking["total_price"], 2):
            raise PaymentError("Payment amount does not match the booking total.")
        balance = self.db.execute("SELECT balance FROM users WHERE id = ?",
                                  (request.payer_id,)).fetchone()["balance"]
        if balance < request.amount:
            raise PaymentError(f"Insufficient balance (${balance:.2f}).")

    def process_payment(self, request):
        """Audit a request, reject failed checks, or delegate an approved payment."""
        masked = f"**** **** **** {str(request.card_last4)[-4:]}"
        try:
            self._validate(request)
        except PaymentError as exc:
            audit_log.warning("REJECTED booking=%s user=%s card=%s reason=%s",
                              request.booking_id, request.payer_id, masked, exc)
            return PaymentResult(False, str(exc))
        result = self._gateway().process_payment(request)
        audit_log.info("APPROVED booking=%s user=%s card=%s amount=%.2f ref=%s",
                       request.booking_id, request.payer_id, masked,
                       request.amount, result.reference)
        return result

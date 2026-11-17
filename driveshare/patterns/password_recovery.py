"""
password_recovery.py  -  CHAIN OF RESPONSIBILITY PATTERN
=======================================================

Problem
-------
Recovering a forgotten password is a sequence of independent security checks.
Every check must pass, in order, before the password may be changed. Writing
this as one big ``if / elif`` function makes it hard to add, remove or reorder
checks and hard to unit-test each one.

Solution
--------
Each check is a *handler* object with the same interface
(``handle(request)``). A handler either rejects the request (stopping the
chain) or forwards it to its successor. The chain is:

    AccountLockoutHandler            (too many failed attempts? -> stop)
      -> SecurityQuestionHandler(1)  (answer to question 1 correct?)
        -> SecurityQuestionHandler(2)
          -> SecurityQuestionHandler(3)
            -> PasswordResetHandler  (strong password? -> save hash, revoke sessions)

The three ``SecurityQuestionHandler`` links are built from the user's three
security questions, as required by the project specification.

Security notes
--------------
* All three answers are submitted together and failures produce one generic
  message, so an attacker cannot learn *which* answer was wrong.
* Each failed attempt increments ``users.failed_recovery``; after
  ``MAX_ATTEMPTS`` failures the account's recovery is locked.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional

from driveshare.security import hash_password, password_problem, verify_answer

MAX_ATTEMPTS = 5
GENERIC_FAILURE = "The answers you provided do not match our records."


@dataclass
class RecoveryRequest:
    """Data passed through the recovery chain for one reset attempt."""

    user_id: int
    answers: List[str]
    new_password: str
    # filled in as the request travels down the chain (useful for the demo)
    passed: List[str] = field(default_factory=list)


@dataclass
class RecoveryResult:
    """Outcome returned by the first handler that rejects, or by chain success."""

    success: bool
    message: str
    failed_at: Optional[str] = None


class RecoveryHandler(ABC):
    """Abstract handler: stores the successor and forwards by default."""

    name = "handler"

    def __init__(self, db):
        """Bind this handler to the database shared by the full chain."""
        self.db = db
        self._next: Optional["RecoveryHandler"] = None

    def set_next(self, handler):
        """Link ``handler`` after this one and return it (enables chaining)."""
        self._next = handler
        return handler

    def handle(self, request) -> RecoveryResult:
        """Run this check, record its pass, and forward to the next handler."""
        result = self.check(request)
        if result is not None:            # this link rejected the request
            return result
        request.passed.append(self.name)
        if self._next is None:
            return RecoveryResult(True, "Password has been reset.")
        return self._next.handle(request)

    @abstractmethod
    def check(self, request) -> Optional[RecoveryResult]:
        """Return a failure ``RecoveryResult`` to stop, or ``None`` to pass."""


class AccountLockoutHandler(RecoveryHandler):
    """Stop recovery before revealing or processing a locked-out account."""

    name = "lockout"

    def check(self, request):
        """Reject unknown users and accounts that reached the failed-attempt limit."""
        row = self.db.execute("SELECT failed_recovery FROM users WHERE id = ?",
                              (request.user_id,)).fetchone()
        if row is None:
            return RecoveryResult(False, GENERIC_FAILURE, self.name)
        if row["failed_recovery"] >= MAX_ATTEMPTS:
            return RecoveryResult(False, "Too many failed attempts. Recovery is locked "
                                         "for this account - please contact support.", self.name)
        return None


class SecurityQuestionHandler(RecoveryHandler):
    """One link per security question (position 1, 2 or 3)."""

    def __init__(self, db, position):
        """Configure the handler for one numbered security question."""
        super().__init__(db)
        self.position = position
        self.name = f"question_{position}"

    def check(self, request):
        """Verify this position's answer and count a failed attempt if incorrect."""
        row = self.db.execute(
            "SELECT answer_hash FROM security_questions WHERE user_id = ? AND position = ?",
            (request.user_id, self.position)).fetchone()
        answer = request.answers[self.position - 1] if len(request.answers) >= self.position else ""
        if row is None or not verify_answer(row["answer_hash"], answer):
            self.db.execute("UPDATE users SET failed_recovery = failed_recovery + 1 WHERE id = ?",
                            (request.user_id,))
            self.db.commit()
            return RecoveryResult(False, GENERIC_FAILURE, self.name)
        return None


class PasswordResetHandler(RecoveryHandler):
    """Final link: validates the new password and stores its hash."""
    name = "reset"

    def __init__(self, db, on_reset=None):
        """Set up the final password update and optional session-revocation hook."""
        super().__init__(db)
        self._on_reset = on_reset          # e.g. revoke sessions via SessionManager

    def check(self, request):
        """Validate and store the new password, resetting lockout on success."""
        problem = password_problem(request.new_password)
        if problem:
            return RecoveryResult(False, problem, self.name)
        self.db.execute("UPDATE users SET password_hash = ?, failed_recovery = 0 WHERE id = ?",
                        (hash_password(request.new_password), request.user_id))
        self.db.commit()
        if self._on_reset:
            self._on_reset(request.user_id)
        return None


def build_recovery_chain(db, on_reset=None):
    """Assemble the chain and return its first link."""
    head = AccountLockoutHandler(db)
    (head.set_next(SecurityQuestionHandler(db, 1))
         .set_next(SecurityQuestionHandler(db, 2))
         .set_next(SecurityQuestionHandler(db, 3))
         .set_next(PasswordResetHandler(db, on_reset)))
    return head

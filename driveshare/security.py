"""
security.py
===========
Small helpers for hashing secrets (passwords and security-question answers).

Passwords and answers are never stored as plain text. Werkzeug's password
hashing functions generate salted, deliberately expensive hashes and perform
the corresponding safe verification.

Recovery answers are normalized before hashing and verification. This makes
formatting differences such as capitalization and repeated whitespace
irrelevant, while still requiring the same answer text.

The password policy is centralized here so account registration and password
recovery can apply identical checks and display consistent error messages.
"""

import re

from werkzeug.security import check_password_hash, generate_password_hash

# Keep the minimum password policy in one place so registration and recovery
# enforce the same requirement.
MIN_PASSWORD_LENGTH = 8


def _coerce_text(value):
    """Convert input to text, treating a missing value as empty input.

    Form fields are normally strings, but callers and tests can pass ``None``
    or other values. Converting ``None`` to ``""`` avoids accidentally
    treating the literal word "None" as a supplied secret.
    """
    return "" if value is None else str(value)


def hash_password(password):
    """Hash a password for storage; do not persist or log the original value.

    Werkzeug generates a random salt and records the algorithm and parameters
    in the returned string, allowing ``check_password_hash`` to verify it
    later without storing the original password.
    """
    return generate_password_hash(_coerce_text(password))


def verify_password(password_hash, password):
    """Return whether a non-empty submitted password matches its stored hash.

    Rejecting empty input before invoking Werkzeug prevents an empty value
    from being accepted as a valid credential, even if a hash was created
    from an empty string elsewhere.
    """
    return bool(password) and check_password_hash(password_hash, _coerce_text(password))


def normalize_answer(answer):
    """Canonicalize an answer before hashing or comparison.

    Trimming removes leading/trailing whitespace, lowercasing ignores case,
    and replacing each run of whitespace with one space makes equivalent
    answers such as ``"Ann  Arbor"`` and ``"ann arbor"`` compare equally.
    """
    return re.sub(r"\s+", " ", _coerce_text(answer).strip().lower())


def hash_answer(answer):
    """Return a salted hash of a normalized security-question answer.

    Normalization must happen before hashing so the same formatting rules are
    applied later by ``verify_answer``.
    """
    return generate_password_hash(normalize_answer(answer))


def verify_answer(answer_hash, answer):
    """Verify a submitted answer after applying the storage-time normalization."""
    return check_password_hash(answer_hash, normalize_answer(answer))


def password_problem(password):
    """Return the first password-policy failure, or ``None`` when the input passes.

    The policy requires a minimum length plus at least one ASCII letter and
    one digit. Returning a message lets registration and recovery show the
    same user-facing validation without duplicating these checks. ``None``
    means the password passes; otherwise the returned string explains the
    first failed rule.
    """
    # Normalize optional/non-string input once, then run each policy rule
    # against the same text value.
    text = _coerce_text(password)
    if len(text) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    # [A-Za-z] intentionally requires an ASCII letter; \d requires a digit.
    # Check after length so callers receive one clear validation message.
    if not re.search(r"[A-Za-z]", text) or not re.search(r"\d", text):
        return "Password must contain at least one letter and one number."
    # No policy rule failed.
    return None

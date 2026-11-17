"""
notification_service.py
=======================
Creates in-app notifications and mirrors each one to a simulated e-mail
outbox (``instance/email_outbox.log``) so the demo can show "email" delivery
without a real mail server.
"""

import os
from datetime import datetime

from flask import current_app


def notify(db, user_id, kind, message, link=None, commit=True):
    """Persist an in-app notification and mirror it to the simulated outbox.

    ``commit=False`` lets a caller include the notification row in a larger
    database transaction; the outbox remains a best-effort local demo channel.
    """
    db.execute("INSERT INTO notifications (user_id, kind, message, link) VALUES (?, ?, ?, ?)",
               (user_id, kind, message, link))
    if commit:
        db.commit()
    _send_simulated_email(db, user_id, kind, message)


def _send_simulated_email(db, user_id, kind, message):
    """Append a plain-text email-like record when an outbox is configured.

    This is deliberately a local simulation, not real email delivery. Calls
    outside an application context skip the outbox because no app config is
    available, while the in-app notification remains the primary channel.
    """
    try:
        outbox = current_app.config.get("EMAIL_OUTBOX")
    except RuntimeError:                  # outside an app context (unit tests)
        outbox = None
    if not outbox:
        return
    row = db.execute("SELECT email FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        return
    directory = os.path.dirname(os.path.abspath(outbox)) or os.getcwd()
    os.makedirs(directory, exist_ok=True)
    with open(outbox, "a", encoding="utf-8") as fh:
        fh.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] To: {row['email']} | "
                 f"Subject: DriveShare {kind} update | {message}\n")


def unread_count(db, user_id):
    """Count unread notification rows for the navigation badge."""
    return db.execute("SELECT COUNT(*) FROM notifications WHERE user_id = ? AND is_read = 0",
                      (user_id,)).fetchone()[0]


def list_for(db, user_id, limit=100):
    """Fetch a user's newest notifications, capped by the requested limit."""
    return db.execute("SELECT * FROM notifications WHERE user_id = ? "
                      "ORDER BY id DESC LIMIT ?", (user_id, limit)).fetchall()


def mark_all_read(db, user_id):
    """Mark every notification belonging to the user as read and commit it."""
    db.execute("UPDATE notifications SET is_read = 1 WHERE user_id = ?", (user_id,))
    db.commit()

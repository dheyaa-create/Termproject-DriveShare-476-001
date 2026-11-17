"""
session_manager.py  -  SINGLETON PATTERN
=======================================

Problem
-------
Every request handler needs to know "who is logged in?". If each part of the
code kept its own record of active sessions they could disagree (one place
thinks the user logged out, another does not), and it would be easy to leak a
session token.

Solution
--------
``SessionManager`` is a Singleton: no matter how many times it is
instantiated, the same single object is returned. That one object is the only
place that

* issues cryptographically random session tokens (``secrets.token_urlsafe``),
* stores only a SHA-256 *hash* of each token (a memory dump never exposes a
  usable token),
* enforces an idle timeout, and
* revokes sessions on logout.

The browser only ever holds the raw token inside Flask's signed (tamper-proof)
cookie.  Passwords themselves are never stored by this class; they are hashed
with a salted key-derivation function in ``services/auth_service.py``.

Usage
-----
    SessionManager() is SessionManager()        # -> True
    token = SessionManager().create_session(user_id)
    SessionManager().get_user_id(token)         # -> user_id (or None)
"""

import hashlib
import secrets
import threading
import time
from dataclasses import dataclass, field


@dataclass
class _SessionRecord:
    """Internal bookkeeping for one logged-in browser session."""
    user_id: int
    created_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)


class SessionManager:
    """Thread-safe Singleton that owns all authenticated user sessions."""

    _instance = None                     # the one and only instance
    _instance_lock = threading.Lock()    # guards first-time creation

    #: idle seconds before a session expires (30 minutes)
    IDLE_TIMEOUT = 30 * 60

    def __new__(cls):
        """
        Classic double-checked locking Singleton.

        ``__new__`` is called before ``__init__``; by returning the cached
        instance we guarantee there is only ever one SessionManager in the
        process, even when Flask serves requests on several threads.
        """
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._sessions = {}           # token_hash -> _SessionRecord
                    instance._lock = threading.RLock()
                    cls._instance = instance
        return cls._instance

    # ------------------------------------------------------------------ #
    # helpers                                                            #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _hash(token):
        """Only token hashes are kept in memory, never raw tokens."""
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    # ------------------------------------------------------------------ #
    # public API                                                         #
    # ------------------------------------------------------------------ #
    def create_session(self, user_id):
        """Start a session for ``user_id`` and return the raw token."""
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._sessions[self._hash(token)] = _SessionRecord(user_id=user_id)
        return token

    def get_user_id(self, token):
        """
        Resolve a token to a user id.

        Returns ``None`` for unknown, revoked or idle-expired tokens. A valid
        lookup refreshes the idle timer (sliding expiration).
        """
        if not token:
            return None
        key = self._hash(token)
        with self._lock:
            record = self._sessions.get(key)
            if record is None:
                return None
            if time.time() - record.last_seen > self.IDLE_TIMEOUT:
                del self._sessions[key]          # expired -> revoke
                return None
            record.last_seen = time.time()
            return record.user_id

    def end_session(self, token):
        """Revoke a session (logout)."""
        if token:
            with self._lock:
                self._sessions.pop(self._hash(token), None)

    def end_all_sessions_for(self, user_id):
        """Revoke every session of a user (used after a password reset)."""
        with self._lock:
            for key in [k for k, r in self._sessions.items() if r.user_id == user_id]:
                del self._sessions[key]

    def active_session_count(self):
        """Number of live sessions (shown on the About page for the demo)."""
        with self._lock:
            return len(self._sessions)

"""
auth.py — the owner's password login, the session cookie and the login rate limit (ADR-018).

The password is kept only as an argon2id hash (``WEB_PASSWORD_HASH``). The session cookie is
signed with a key derived from that hash, so setting a new password ends every session.
Endpoints that need a logged-in owner depend on ``require_session``.
"""

import hashlib
import time
from collections import defaultdict, deque
from collections.abc import Callable

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import HTTPException, Request
from itsdangerous import BadSignature, URLSafeTimedSerializer

SESSION_COOKIE = "session"
SESSION_MAX_AGE_S = 7 * 24 * 60 * 60
# Failed logins per client allowed in one window; more are refused until the window passes.
MAX_FAILED_LOGINS = 5
FAILED_LOGIN_WINDOW_S = 60.0


class LoginRateLimit:
    """Failed logins per client in a sliding window, in memory."""

    def __init__(self, clock: Callable[[], float] = time.monotonic,
                 max_failures: int = MAX_FAILED_LOGINS, window_s: float = FAILED_LOGIN_WINDOW_S):
        self._clock = clock
        self._max = max_failures
        self._window = window_s
        self._failures: dict[str, deque[float]] = defaultdict(deque)

    def _recent(self, client: str) -> deque[float]:
        failures = self._failures[client]
        while failures and failures[0] <= self._clock() - self._window:
            failures.popleft()
        return failures

    def blocked(self, client: str) -> bool:
        return len(self._recent(client)) >= self._max

    def record_failure(self, client: str) -> None:
        self._recent(client).append(self._clock())


class Auth:
    """Checks the password and issues and reads session cookies, for one password hash."""

    def __init__(self, password_hash: str, *, secure_cookie: bool, clock: Callable[[], float] = time.monotonic):
        self._hash = password_hash
        self.secure_cookie = secure_cookie
        self.rate_limit = LoginRateLimit(clock)
        # The hash is secret (only in .env) and changes with the password: a key derived from it
        # signs the cookies, so a new password makes every earlier cookie unreadable.
        key = hashlib.sha256(b"agent-web-session\0" + password_hash.encode()).hexdigest()
        self._serializer = URLSafeTimedSerializer(key, salt="session")

    def password_matches(self, password: str) -> bool:
        try:
            return PasswordHasher().verify(self._hash, password)
        except (VerificationError, InvalidHashError):
            return False

    def new_session(self) -> str:
        return self._serializer.dumps({"owner": True})

    def session_valid(self, cookie: str | None) -> bool:
        if not cookie:
            return False
        try:
            return self._serializer.loads(cookie, max_age=SESSION_MAX_AGE_S) == {"owner": True}
        except BadSignature:
            return False


def require_session(request: Request) -> None:
    """FastAPI dependency: refuse the request (401) unless it carries a valid session cookie."""
    auth: Auth = request.app.state.auth
    if not auth.session_valid(request.cookies.get(SESSION_COOKIE)):
        raise HTTPException(status_code=401, detail="Not logged in.")

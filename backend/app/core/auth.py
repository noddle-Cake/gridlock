"""Sign-in: one account from the environment, a signed session cookie, and a login limiter.

Set AUTH_USERNAME and AUTH_PASSWORD to turn protection on; with either unset the app is
open (local development and tests). Every API route then needs the session cookie except
the ones in PUBLIC_PATHS; the frontend shows its sign-in screen on a 401.

The cookie holds "username|expiry" signed with HMAC-SHA256 under AUTH_SECRET (a random
per-process key when unset, so restarts sign everyone out).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
import time
from collections import defaultdict, deque
from collections.abc import Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.config import Settings

log = logging.getLogger(__name__)

COOKIE_NAME = "gridmerge_session"
# Reachable without a session: the deploy smoke test and the sign-in flow itself.
PUBLIC_PATHS = {"/health", "/auth/login", "/auth/logout", "/auth/session"}
MAX_FAILURES = 5  # failed logins per client ...
FAILURE_WINDOW_S = 15 * 60  # ... within this window, before it is locked out


class Auth:
    def __init__(self, settings: Settings, *, clock: Callable[[], float] = time.time) -> None:
        self.username = settings.auth_username.strip()
        self._password = settings.auth_password
        self.enabled = bool(self.username and self._password)
        self._key = (settings.auth_secret or secrets.token_hex(32)).encode()
        self._ttl = settings.auth_session_hours * 3600
        self._clock = clock
        self._failures: dict[str, deque[float]] = defaultdict(deque)

    # ------------------------------------------------------------ credentials

    def check(self, username: str, password: str) -> bool:
        """Constant-time comparison; the username ignores case and surrounding spaces."""
        user_ok = hmac.compare_digest(username.strip().lower().encode(),
                                      self.username.lower().encode())
        pass_ok = hmac.compare_digest(password.encode(), self._password.encode())
        return user_ok and pass_ok

    # ------------------------------------------------------------ session tokens

    def _sign(self, payload: bytes) -> str:
        return hmac.new(self._key, payload, hashlib.sha256).hexdigest()

    def issue(self) -> str:
        expires = int(self._clock() + self._ttl)
        payload = f"{self.username}|{expires}".encode()
        return f"{base64.urlsafe_b64encode(payload).decode()}.{self._sign(payload)}"

    def verify(self, token: str | None) -> str | None:
        """The signed-in username, or None for a missing, tampered, or expired token."""
        if not token or "." not in token:
            return None
        encoded, sig = token.rsplit(".", 1)
        try:
            payload = base64.urlsafe_b64decode(encoded.encode())
        except (ValueError, TypeError):
            return None
        if not hmac.compare_digest(sig, self._sign(payload)):
            return None
        username, _, expires = payload.decode(errors="replace").rpartition("|")
        if not expires.isdigit() or int(expires) < self._clock():
            return None
        return username if username == self.username else None

    @property
    def max_age(self) -> int:
        return int(self._ttl)

    # ------------------------------------------------------------ login limiter

    def _recent(self, client: str) -> deque[float]:
        q = self._failures[client]
        cutoff = self._clock() - FAILURE_WINDOW_S
        while q and q[0] < cutoff:
            q.popleft()
        return q

    def locked_out(self, client: str) -> bool:
        return len(self._recent(client)) >= MAX_FAILURES

    def record_failure(self, client: str) -> None:
        self._recent(client).append(self._clock())

    def clear_failures(self, client: str) -> None:
        self._failures.pop(client, None)


def client_id(request: Request) -> str:
    """The caller's address. Behind Caddy it is the last X-Forwarded-For hop (the one
    Caddy added); a client can prepend fake hops but not replace that one."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def _route_path(request: Request) -> str:
    """Path within this app, whether it runs alone or mounted under /api (app/serve.py)."""
    path = request.url.path
    root = request.scope.get("root_path", "")
    if root and path.startswith(root):
        return path[len(root):] or "/"
    return path


def install_auth(app: FastAPI, auth: Auth) -> None:
    app.state.auth = auth
    if not auth.enabled:
        log.warning("AUTH_USERNAME/AUTH_PASSWORD not set: GridMerge is open without sign-in")
        return

    @app.middleware("http")
    async def require_session(request: Request, call_next):
        if request.method == "OPTIONS" or _route_path(request) in PUBLIC_PATHS:
            return await call_next(request)
        if auth.verify(request.cookies.get(COOKIE_NAME)) is None:
            return JSONResponse(
                status_code=401,
                content={"error": {"code": "unauthenticated",
                                   "message": "Sign in to use GridMerge."}},
            )
        return await call_next(request)

"""Who is calling /v1: a server with an API key, or a browser with a guest session cookie.

The browser never holds an API key, because anything shipped to a browser can be read. It gets a guest session
instead: a random id with an expiry, signed with HMAC-SHA256, in an HttpOnly cookie that scripts cannot read and that
SameSite=Strict keeps off cross-site requests. Keys are compared in constant time, and several keys allow rotation.
"""

import hashlib
import hmac
import secrets
import time
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyHeader

from app.core.dependencies import get_settings
from app.middleware.rate_limit import key_id
from app.settings import Settings

GUEST_COOKIE = "tiketa_guest"
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


class GuestSessions:
    def __init__(self, secret: str, days: int) -> None:
        self._secret = secret.encode()
        self.max_age_seconds = days * 86_400

    def issue(self) -> str:
        guest_id = secrets.token_urlsafe(12)
        expires = int(time.time()) + self.max_age_seconds
        return f"{guest_id}.{expires}.{self._sign(guest_id, expires)}"

    def read(self, token: str | None) -> str | None:
        """The guest id of a token this server signed and that has not expired, otherwise None."""
        parts = (token or "").split(".")
        if len(parts) != 3 or not parts[1].isdigit():
            return None
        guest_id, expires, signature = parts[0], int(parts[1]), parts[2]
        if not hmac.compare_digest(signature, self._sign(guest_id, expires)) or expires < time.time():
            return None
        return guest_id

    def _sign(self, guest_id: str, expires: int) -> str:
        return hmac.new(self._secret, f"{guest_id}.{expires}".encode(), hashlib.sha256).hexdigest()


def get_guest_sessions(request: Request) -> GuestSessions:
    sessions: GuestSessions = request.app.state.guest_sessions
    return sessions


async def authenticate(
    request: Request,
    key: Annotated[str | None, Depends(api_key_header)],
    settings: Annotated[Settings, Depends(get_settings)],
    guests: Annotated[GuestSessions, Depends(get_guest_sessions)],
) -> str:
    """The caller's name, kept on the request for the rate limit. Every /v1 route depends on it."""
    accepted = settings.api_key_list
    guest_id = guests.read(request.cookies.get(GUEST_COOKIE))
    if key:
        if accepted and not any(secrets.compare_digest(key.encode(), candidate.encode()) for candidate in accepted):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing or invalid API key")
        caller = key_id(key)
    elif guest_id is not None:
        caller = f"guest:{guest_id}"
    elif not accepted:  # auth disabled (local)
        caller = f"ip:{request.client.host if request.client else 'unknown'}"
    else:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Send an API key, or start a guest session at /auth/guest")
    request.state.caller = caller
    return caller

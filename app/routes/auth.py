"""Guest sessions for browsers: the cookie a browser calls /v1 with instead of an API key."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from app.core.dependencies import enforce_rate_limit, get_settings
from app.middleware.auth import GUEST_COOKIE, GuestSessions, get_guest_sessions
from app.settings import Settings

router = APIRouter(prefix="/auth", tags=["auth"], dependencies=[Depends(enforce_rate_limit)])  # per client address


@router.post("/guest", status_code=204)
async def start_guest_session(
    request: Request,
    response: Response,
    guests: Annotated[GuestSessions, Depends(get_guest_sessions)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    """Sets a signed guest session cookie, or keeps the one the browser already has while it is valid."""
    if guests.read(request.cookies.get(GUEST_COOKIE)) is not None:
        return
    response.set_cookie(
        GUEST_COOKIE,
        guests.issue(),
        max_age=guests.max_age_seconds,
        httponly=True,  # scripts cannot read it, so an injected script cannot carry it away
        samesite="strict",  # other sites cannot make the browser send it
        secure=settings.environment not in ("local", "test"),  # HTTPS only once deployed
        path="/",
    )

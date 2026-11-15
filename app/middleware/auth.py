"""Who is calling /v1. The agent keeps no keys and signs no sessions: the booking API does, and is asked each time.

A request carries an API key (servers) or the guest session cookie the booking API set (browsers). Both are passed
to the booking API, which names the caller or refuses. The same credentials then travel with every tool call of the
turn, so a booking made in the chat is made as that person and no one else.
"""

from typing import Annotated

from fastapi import Depends, Request

from app.core.dependencies import get_booking_api
from app.repositories.booking_api import BookingApi
from app.schemas.cinema import Caller

API_KEY_HEADER = "X-API-Key"
GUEST_COOKIE = "tiketa_guest"


def credentials_of(request: Request) -> dict[str, str]:
    """The caller's credentials as the booking API reads them, and nothing else of the request."""
    key = request.headers.get(API_KEY_HEADER)
    guest_token = request.cookies.get(GUEST_COOKIE)
    credentials = {API_KEY_HEADER: key} if key else {}
    return credentials | ({"Cookie": f"{GUEST_COOKIE}={guest_token}"} if guest_token else {})


async def authenticate(request: Request, api: Annotated[BookingApi, Depends(get_booking_api)]) -> Caller:
    """The caller, kept on the request for the rate limit. Every /v1 route depends on it."""
    credentials = credentials_of(request)
    caller = Caller(name=await api.caller_name(credentials), credentials=credentials)
    request.state.caller = caller.name
    return caller

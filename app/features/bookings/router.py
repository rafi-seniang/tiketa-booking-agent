"""Book seats from the form, and list the caller's bookings from the form and the chat together."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel

from app.core.dependencies import get_now, get_settings, get_store
from app.core.errors import Conflict
from app.middleware.rate_limit import caller_of
from app.repositories.cinema import CinemaStore
from app.schemas.cinema import Booking, BookingRequest, CustomerName, SeatIds
from app.settings import Settings

router = APIRouter(prefix="/bookings", tags=["bookings"])
Store = Annotated[CinemaStore, Depends(get_store)]
Caller = Annotated[str, Depends(caller_of)]
RECENT_BOOKINGS = 20


class BookingIn(BaseModel):
    showtime_id: int
    seats: SeatIds
    customer_name: CustomerName


@router.post("", status_code=201)
async def book(
    body: BookingIn,
    store: Store,
    caller: Caller,
    now: Annotated[datetime, Depends(get_now)],
    settings: Annotated[Settings, Depends(get_settings)],
    idempotency_key: Annotated[str, Header(min_length=8, max_length=64)],
) -> Booking:
    """Books every seat or none. A retried request with the same Idempotency-Key gets the first booking back."""
    if len(body.seats) > settings.max_seats_per_booking:
        raise Conflict(f"At most {settings.max_seats_per_booking} seats per booking")
    request = BookingRequest(
        idempotency_key=f"web:{caller}:{idempotency_key}",  # a key is unique per caller, not across callers
        owner=caller,
        channel="web",
        showtime_id=body.showtime_id,
        seats=body.seats,
        customer_name=body.customer_name,
    )
    return await store.book(request, now)


@router.get("")
async def my_bookings(store: Store, caller: Caller) -> list[Booking]:
    """The caller's latest bookings, from the form and the chat, newest first."""
    return await store.bookings_for_owner(caller, RECENT_BOOKINGS)

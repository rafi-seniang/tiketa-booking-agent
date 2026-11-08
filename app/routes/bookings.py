"""Book seats from the form, and list the caller's bookings from the form and the chat together."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header

from app.controllers.bookings import BookingController
from app.core.dependencies import get_booking_controller, get_now
from app.middleware.rate_limit import caller_of
from app.schemas.cinema import Booking, BookingForm

router = APIRouter(prefix="/bookings", tags=["bookings"])
Controller = Annotated[BookingController, Depends(get_booking_controller)]
Caller = Annotated[str, Depends(caller_of)]


@router.post("", status_code=201)
async def book(
    body: BookingForm,
    controller: Controller,
    caller: Caller,
    now: Annotated[datetime, Depends(get_now)],
    idempotency_key: Annotated[str, Header(min_length=8, max_length=64)],
) -> Booking:
    """Books every seat or none. A retried request with the same Idempotency-Key gets the first booking back."""
    return await controller.book(body, caller, idempotency_key, now)


@router.get("")
async def my_bookings(controller: Controller, caller: Caller) -> list[Booking]:
    """The caller's latest bookings, from the form and the chat, newest first."""
    return await controller.recent(caller)

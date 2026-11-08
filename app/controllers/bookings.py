"""The booking form: the same seats and prices as the chat, chosen by hand. No model is called."""

from datetime import datetime

from app.core.errors import Conflict
from app.repositories.cinema import CinemaStore
from app.schemas.cinema import Booking, BookingForm, BookingRequest

RECENT_BOOKINGS = 20


class BookingController:
    def __init__(self, store: CinemaStore, max_seats: int) -> None:
        self._store = store
        self._max_seats = max_seats

    async def book(self, form: BookingForm, caller: str, idempotency_key: str, now: datetime) -> Booking:
        """Books every seat or none. A retried request with the same key gets the first booking back."""
        if len(form.seats) > self._max_seats:
            raise Conflict(f"At most {self._max_seats} seats per booking")
        request = BookingRequest(
            idempotency_key=f"web:{caller}:{idempotency_key}",  # a key is unique per caller, not across callers
            owner=caller,
            channel="web",
            showtime_id=form.showtime_id,
            seats=form.seats,
            customer_name=form.customer_name,
        )
        return await self._store.book(request, now)

    async def recent(self, caller: str) -> list[Booking]:
        """The caller's latest bookings, from the form and the chat, newest first."""
        return await self._store.bookings_for_owner(caller, RECENT_BOOKINGS)

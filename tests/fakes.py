import itertools
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from app.core.errors import Conflict, NotFound
from app.schemas.cinema import (
    Booking,
    BookingOrder,
    Caller,
    Cinema,
    Movie,
    SeatMap,
    SeatRowView,
    SeatView,
    Showtime,
    Week,
)
from app.utils.clock import local_text

CINEMA_TIMEZONE = ZoneInfo("Asia/Jakarta")
ROWS = "ABCDEFGHIJLM"
SEATS_PER_ROW = 18
DUNE = Movie(
    id=9,
    title="Dune: Part Two",
    synopsis="Paul Atreides joins the Fremen.",
    release_year=2024,
    genres=["Adventure", "Drama", "Science Fiction"],
    studio_number=9,
)


class ScriptedChatModel(BaseChatModel):
    """Answers with the replies it was given, in order, and keeps what it was sent. Raises when a reply is one."""

    replies: list[AIMessage | Exception]
    received: list[list[BaseMessage]] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.received.append(list(messages))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return ChatResult(generations=[ChatGeneration(message=reply)])

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedChatModel":
        return self


def calls(*tool_calls: tuple[str, dict[str, Any]]) -> AIMessage:
    """A model reply that calls tools, with ids call_<name>."""
    return AIMessage(
        content="",
        tool_calls=[
            {"name": name, "args": args, "id": f"call_{name}", "type": "tool_call"} for name, args in tool_calls
        ],
        usage_metadata={"input_tokens": 100, "output_tokens": 10, "total_tokens": 110},
    )


def says(text: str) -> AIMessage:
    return AIMessage(content=text, usage_metadata={"input_tokens": 120, "output_tokens": 20, "total_tokens": 140})


class FakeBookingApi:
    """The booking service in memory, with its rules: a seat is sold once, a key books once, an owner sees its own.

    It has the agent's client's methods, keeps what each caller did, and can be told to refuse a caller.
    """

    def __init__(self, now: datetime) -> None:
        day = now.astimezone(CINEMA_TIMEZONE).date()
        starts = [
            datetime.combine(day, datetime.min.time(), CINEMA_TIMEZONE) + timedelta(hours=h) for h in (12, 15, 18, 21)
        ]
        self.showtimes = [
            Showtime(
                id=number,
                movie_id=DUNE.id,
                movie_title=DUNE.title,
                studio_number=DUNE.studio_number,
                starts_at=start.astimezone(UTC),
                starts_at_local=local_text(start, CINEMA_TIMEZONE),
                price_idr=60_000,
                seats_left=len(ROWS) * SEATS_PER_ROW,
            )
            for number, start in enumerate(starts, start=1)
        ]
        self.now = now
        self.bookings: list[tuple[str, str, Booking, str]] = []  # owner, idempotency key, booking, session id
        self.codes = itertools.count(1)
        self.seen_callers: list[Caller] = []

    async def caller_name(self, credentials: dict[str, str]) -> str:
        return f"key:{credentials.get('X-API-Key', 'none')}"

    async def cinema(self, caller: Caller) -> Cinema:
        today = self.now.astimezone(CINEMA_TIMEZONE).date()
        week = Week(days=[today], today=today, is_published=True)
        return Cinema(name="Tiketa Cinema", timezone="Asia/Jakarta", max_seats_per_booking=8, week=week)

    async def list_movies(self, caller: Caller) -> list[Movie]:
        return [DUNE]

    async def get_movie(self, movie_id: int, caller: Caller) -> Movie:
        if movie_id != DUNE.id:
            raise NotFound(f"There is no film with id {movie_id}")
        return DUNE

    async def showtimes_on(self, day: date, movie_id: int | None, caller: Caller) -> list[Showtime]:
        self.seen_callers.append(caller)
        return [
            showtime
            for showtime in self.showtimes
            if showtime.starts_at.astimezone(CINEMA_TIMEZONE).date() == day and showtime.starts_at > self.now
        ]

    async def get_showtime(self, showtime_id: int, caller: Caller) -> Showtime:
        found = [showtime for showtime in self.showtimes if showtime.id == showtime_id]
        if not found:
            raise NotFound(f"There is no showtime with id {showtime_id}")
        return found[0]

    def taken(self, showtime_id: int) -> set[str]:
        return {
            seat for _, _, booking, _ in self.bookings if booking.showtime.id == showtime_id for seat in booking.seats
        }

    async def seat_map(self, showtime_id: int, caller: Caller) -> SeatMap:
        showtime = await self.get_showtime(showtime_id, caller)
        taken = self.taken(showtime_id)
        rows = [
            SeatRowView(
                row=row,
                seats=[SeatView(id=f"{row}{n}", is_taken=f"{row}{n}" in taken) for n in range(1, SEATS_PER_ROW + 1)],
            )
            for row in ROWS
        ]
        return SeatMap(showtime=showtime, rows=rows, aisle_after_seat=9, walkway_before_row="L")

    async def book(self, order: BookingOrder, idempotency_key: str, caller: Caller) -> Booking:
        self.seen_callers.append(caller)
        again = [booking for owner, key, booking, _ in self.bookings if (owner, key) == (caller.name, idempotency_key)]
        if again:
            return again[0]
        taken_now = [seat for seat in order.seats if seat in self.taken(order.showtime_id)]
        if taken_now:
            raise Conflict(f"Already taken by someone else: {', '.join(taken_now)}")
        showtime = await self.get_showtime(order.showtime_id, caller)
        booking = Booking(
            code=f"TK{next(self.codes):08d}",
            channel="chat",
            showtime=showtime,
            seats=order.seats,
            customer_name=order.customer_name,
            total_price_idr=showtime.price_idr * len(order.seats),
            created_at=self.now,
        )
        self.bookings.append((caller.name, idempotency_key, booking, order.session_id))
        return booking

    async def bookings_of_session(self, session_id: str, caller: Caller) -> list[Booking]:
        return [
            booking for owner, _, booking, session in self.bookings if (owner, session) == (caller.name, session_id)
        ]

    async def someone_else_books(self, showtime: Showtime, seats: list[str]) -> None:
        other = Caller(name="key:someone-else", credentials={})
        order = BookingOrder(showtime_id=showtime.id, seats=seats, customer_name="X", session_id="another")
        await self.book(order, f"other-{len(self.bookings)}", other)

"""The agent's tools. Reads are free. Changes go through checks in code, and a booking waits for the user's yes."""

import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

from langchain.tools import BaseTool, ToolRuntime, tool
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.types import Command, interrupt
from pydantic import BaseModel, Field

from app.cinema.clock import local_text
from app.cinema.schemas import BookingRequest, CustomerName, SeatIds, Showtime
from app.cinema.seat_layout import SEAT_MAP_LEGEND, seat_map_text
from app.cinema.store import CinemaStore
from app.core.errors import Conflict
from app.features.chat.schemas import BookingSummary, ConfirmationAnswer
from app.features.chat.state import CLEARED_AFTER_BOOKING, ChatContext, Draft, TiketaState, merge_draft, missing_fields

Runtime = ToolRuntime[ChatContext, TiketaState]


class FindShowtimesArgs(BaseModel):
    day: date = Field(description="The day, in cinema time, as YYYY-MM-DD")
    movie_id: int | None = Field(default=None, description="Only this film. Leave it out for every film")


class MovieArgs(BaseModel):
    movie_id: int


class ShowtimeArgs(BaseModel):
    showtime_id: int


class UpdateBookingArgs(BaseModel):
    showtime_id: int | None = Field(default=None, description="The chosen showtime, from find_showtimes")
    seats: SeatIds | None = Field(default=None, description="Every seat of the booking, ids as in the seat map")
    customer_name: CustomerName | None = Field(default=None, description="The name the booking is under")


def showtime_label(showtime: Showtime, cinema_timezone: ZoneInfo) -> str:
    when = local_text(showtime.starts_at, cinema_timezone)
    return f"{showtime.movie_title}, {when}, studio {showtime.studio_number}, {showtime.price_idr} IDR per seat"


def draft_text(draft: Draft) -> str:
    missing = missing_fields(draft)
    lines = [
        f"Showtime: {draft.get('showtime_label') or 'not chosen'}",
        f"Seats: {', '.join(draft.get('seats') or []) or 'not chosen'}",
        f"Name: {draft.get('customer_name') or 'not given'}",
        f"Still needed: {', '.join(missing)}" if missing else "Ready: call book_tickets when the user wants to book",
    ]
    return "\n".join(lines)


def refuse_started_showtime(showtime: Showtime, now: datetime) -> None:
    if showtime.starts_at <= now:
        raise Conflict("This showtime has already started")


def build_tools(store: CinemaStore, cinema_timezone: ZoneInfo, max_seats: int) -> list[BaseTool]:
    async def refuse_taken_seats(showtime_id: int, seat_ids: list[str]) -> None:
        taken = await store.taken_seat_ids(showtime_id)
        taken_now = [seat_id for seat_id in seat_ids if seat_id in taken]
        if taken_now:
            raise Conflict(f"Already taken: {', '.join(taken_now)}. Read the seat map again")

    @tool(args_schema=FindShowtimesArgs)
    async def find_showtimes(day: date, runtime: Runtime, movie_id: int | None = None) -> str:
        """Showtimes on one day that have not started yet, with price per seat and seats left."""
        showtimes = await store.showtimes_on(day, runtime.context.now, movie_id)
        if not showtimes:
            return f"No showtimes left on {day:%A %d %B %Y}."
        rows = [
            {
                "showtime_id": showtime.id,
                "film": showtime.movie_title,
                "movie_id": showtime.movie_id,
                "starts": local_text(showtime.starts_at, cinema_timezone),
                "studio": showtime.studio_number,
                "price_idr": showtime.price_idr,
                "seats_left": showtime.seats_left,
            }
            for showtime in showtimes
        ]
        return json.dumps(rows, ensure_ascii=False)

    @tool(args_schema=MovieArgs)
    async def get_movie_details(movie_id: int) -> str:
        """A film's synopsis, year, genres and studio."""
        movie = await store.get_movie(movie_id)
        return movie.model_dump_json(exclude={"poster_url", "trailer_youtube_id"})

    @tool(args_schema=ShowtimeArgs)
    async def get_seat_map(showtime_id: int) -> str:
        """The seat map of a showtime, with the seats already taken. Read it before choosing seats."""
        showtime = await store.get_showtime(showtime_id)
        taken = await store.taken_seat_ids(showtime_id)
        return f"{showtime_label(showtime, cinema_timezone)}\n{SEAT_MAP_LEGEND}\n{seat_map_text(taken)}"

    @tool(args_schema=UpdateBookingArgs)
    async def update_booking(
        runtime: Runtime,
        showtime_id: int | None = None,
        seats: list[str] | None = None,
        customer_name: str | None = None,
    ) -> Command[None]:
        """Sets the showtime, the seats and the name of the booking. Pass only what changes."""
        draft = runtime.state.get("draft") or Draft()
        change = Draft()
        chosen_showtime_id = draft.get("showtime_id")
        if showtime_id is not None:
            showtime = await store.get_showtime(showtime_id)
            refuse_started_showtime(showtime, runtime.context.now)
            change["showtime_id"] = showtime.id
            change["showtime_label"] = showtime_label(showtime, cinema_timezone)
            if showtime.id != chosen_showtime_id:  # seats belong to one showtime
                change["seats"] = []
            chosen_showtime_id = showtime.id
        if seats is not None:
            if chosen_showtime_id is None:
                raise Conflict("Choose a showtime before the seats")
            if len(seats) > max_seats:
                raise Conflict(f"At most {max_seats} seats per booking")
            await refuse_taken_seats(chosen_showtime_id, seats)
            change["seats"] = seats
        if customer_name is not None:
            change["customer_name"] = customer_name
        result = draft_text(merge_draft(draft, change))
        return Command(update={"draft": change, "messages": [ToolMessage(result, tool_call_id=runtime.tool_call_id)]})

    @tool
    async def book_tickets(runtime: Runtime) -> Command[None]:
        """Asks the user to confirm the booking in progress, then books it. Call it alone, once nothing is missing."""
        last_message = runtime.state["messages"][-1]
        if isinstance(last_message, AIMessage) and len(last_message.tool_calls) > 1:
            raise Conflict("Call book_tickets on its own, after the other tool calls have finished")
        draft = runtime.state.get("draft") or Draft()
        missing = missing_fields(draft)
        if missing:
            raise Conflict(f"Still needed: {', '.join(missing)}")
        showtime_id, seat_ids, customer_name = draft["showtime_id"], draft["seats"], draft["customer_name"]
        if showtime_id is None or customer_name is None:  # missing_fields already refused these, for the type checker
            raise Conflict("The booking is not complete")
        showtime = await store.get_showtime(showtime_id)
        now = runtime.context.now
        refuse_started_showtime(showtime, now)
        await refuse_taken_seats(showtime_id, seat_ids)
        summary = BookingSummary(
            showtime_id=showtime.id,
            movie_title=showtime.movie_title,
            starts_at=showtime.starts_at,
            starts_at_local=local_text(showtime.starts_at, cinema_timezone),
            studio_number=showtime.studio_number,
            seats=seat_ids,
            customer_name=customer_name,
            price_per_seat_idr=showtime.price_idr,
            total_price_idr=showtime.price_idr * len(seat_ids),
        )
        # Pauses the conversation until the user answers. On resume this tool runs again from the top
        answer = interrupt(
            {"kind": "booking_confirmation", "summary": summary.model_dump(mode="json")},
            response_schema=ConfirmationAnswer,
        )
        typed_reply = [HumanMessage(answer.user_message)] if answer.user_message else []
        if not answer.approved:
            if answer.user_message:
                outcome = "The user wrote a reply instead of confirming, so nothing was booked. Act on their message."
            else:
                outcome = "The user pressed Cancel on the summary, so nothing was booked. Tell them it is cancelled."
            declined = ToolMessage(outcome, tool_call_id=runtime.tool_call_id)
            return Command(update={"messages": [declined, *typed_reply]})
        if runtime.tool_call_id is None:
            raise RuntimeError("book_tickets runs only as a tool call, whose id keeps the booking idempotent")
        request = BookingRequest(
            idempotency_key=runtime.tool_call_id,
            owner=runtime.context.owner,
            channel="chat",
            session_id=runtime.context.session_id,
            showtime_id=showtime_id,
            seats=seat_ids,
            customer_name=customer_name,
        )
        booking = await store.book(request, now)
        runtime.stream_writer({"booking": booking.model_dump(mode="json")})
        booked = ToolMessage(
            f"The user confirmed and it is booked. Booking code {booking.code}: "
            f"{showtime_label(booking.showtime, cinema_timezone)}, seats "
            f"{', '.join(booking.seats)}, name {booking.customer_name}, total {booking.total_price_idr} IDR.",
            tool_call_id=runtime.tool_call_id,
        )
        return Command(update={"draft": CLEARED_AFTER_BOOKING, "messages": [booked, *typed_reply]})

    @tool
    async def list_my_bookings(runtime: Runtime) -> str:
        """The bookings made in this conversation."""
        bookings = await store.bookings_for_session(runtime.context.session_id)
        if not bookings:
            return "No bookings in this conversation yet."
        return json.dumps([booking.model_dump(mode="json") for booking in bookings], ensure_ascii=False)

    return [find_showtimes, get_movie_details, get_seat_map, update_booking, book_tickets, list_my_bookings]

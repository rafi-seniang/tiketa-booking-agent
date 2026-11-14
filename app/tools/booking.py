"""The agent's tools. Reads are free. Changes go through checks in code, and a booking waits for the user's yes.

Films, showtimes, seats and bookings belong to the booking API. Every tool asks it as the person in the conversation.
"""

import json
from datetime import date, datetime

from langchain.tools import BaseTool, ToolRuntime, tool
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.types import Command, interrupt
from pydantic import BaseModel, Field

from app.core.errors import Conflict
from app.repositories.booking_api import BookingApi, idempotency_key_of
from app.schemas.agent import CLEARED_AFTER_BOOKING, ChatContext, Draft, TiketaState, merge_draft, missing_fields
from app.schemas.chat import BookingSummary, ConfirmationAnswer
from app.schemas.cinema import BookingOrder, Caller, CustomerName, SeatIds, Showtime
from app.utils.seat_map import seat_ids_of, seat_map_legend, seat_map_text, taken_seat_ids_of

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


def showtime_label(showtime: Showtime) -> str:
    return (
        f"{showtime.movie_title}, {showtime.starts_at_local}, studio {showtime.studio_number}, "
        f"{showtime.price_idr} IDR per seat"
    )


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


def build_tools(api: BookingApi, max_seats: int) -> list[BaseTool]:
    async def refuse_unknown_or_taken_seats(showtime_id: int, seat_ids: list[str], caller: Caller) -> None:
        seat_map = await api.seat_map(showtime_id, caller)
        known = seat_ids_of(seat_map)
        unknown = [seat_id for seat_id in seat_ids if seat_id not in known]
        if unknown:
            raise Conflict(
                f"{', '.join(unknown)} is not a seat in this studio. Seat ids look like D7: a row letter, then a number"
            )
        taken = taken_seat_ids_of(seat_map)
        taken_now = [seat_id for seat_id in seat_ids if seat_id in taken]
        if taken_now:
            raise Conflict(f"Already taken: {', '.join(taken_now)}. Read the seat map again")

    @tool(args_schema=FindShowtimesArgs)
    async def find_showtimes(day: date, runtime: Runtime, movie_id: int | None = None) -> str:
        """Showtimes on one day that have not started yet, with price per seat and seats left."""
        showtimes = await api.showtimes_on(day, movie_id, runtime.context.caller)
        if not showtimes:
            return f"No showtimes left on {day:%A %d %B %Y}."
        rows = [
            {
                "showtime_id": showtime.id,
                "film": showtime.movie_title,
                "movie_id": showtime.movie_id,
                "starts": showtime.starts_at_local,
                "studio": showtime.studio_number,
                "price_idr": showtime.price_idr,
                "seats_left": showtime.seats_left,
            }
            for showtime in showtimes
        ]
        return json.dumps(rows, ensure_ascii=False)

    @tool(args_schema=MovieArgs)
    async def get_movie_details(movie_id: int, runtime: Runtime) -> str:
        """A film's synopsis, year, genres and studio."""
        movie = await api.get_movie(movie_id, runtime.context.caller)
        return movie.model_dump_json()

    @tool(args_schema=ShowtimeArgs)
    async def get_seat_map(showtime_id: int, runtime: Runtime) -> str:
        """The seat map of a showtime, with the seats already taken. Read it before choosing seats."""
        seat_map = await api.seat_map(showtime_id, runtime.context.caller)
        return f"{showtime_label(seat_map.showtime)}\n{seat_map_legend(seat_map)}\n{seat_map_text(seat_map)}"

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
            showtime = await api.get_showtime(showtime_id, runtime.context.caller)
            refuse_started_showtime(showtime, runtime.context.now)
            change["showtime_id"] = showtime.id
            change["showtime_label"] = showtime_label(showtime)
            if showtime.id != chosen_showtime_id:  # seats belong to one showtime
                change["seats"] = []
            chosen_showtime_id = showtime.id
        if seats is not None:
            if chosen_showtime_id is None:
                raise Conflict("Choose a showtime before the seats")
            if len(seats) > max_seats:
                raise Conflict(f"At most {max_seats} seats per booking")
            await refuse_unknown_or_taken_seats(chosen_showtime_id, seats, runtime.context.caller)
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
        context = runtime.context
        showtime = await api.get_showtime(showtime_id, context.caller)
        refuse_started_showtime(showtime, context.now)
        await refuse_unknown_or_taken_seats(showtime_id, seat_ids, context.caller)
        summary = BookingSummary(
            showtime_id=showtime.id,
            movie_title=showtime.movie_title,
            starts_at=showtime.starts_at,
            starts_at_local=showtime.starts_at_local,
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
                outcome = (
                    "The user pressed Cancel on the summary, so nothing was booked. No seat is held or set aside "
                    "for them: seats stay free for anyone until a booking is made. Tell them it is cancelled."
                )
            declined = ToolMessage(outcome, tool_call_id=runtime.tool_call_id)
            return Command(update={"messages": [declined, *typed_reply]})
        if runtime.tool_call_id is None:
            raise RuntimeError("book_tickets runs only as a tool call, whose id keeps the booking idempotent")
        order = BookingOrder(
            showtime_id=showtime_id, seats=seat_ids, customer_name=customer_name, session_id=context.session_id
        )
        # The booking API decides: it prices the seats itself and refuses any that were sold in the meantime
        idempotency_key = idempotency_key_of(context.session_id, runtime.tool_call_id)
        booking = await api.book(order, idempotency_key, context.caller)
        runtime.stream_writer({"booking": booking.model_dump(mode="json")})
        booked = ToolMessage(
            f"The user confirmed and it is booked. Booking code {booking.code}: "
            f"{showtime_label(booking.showtime)}, seats "
            f"{', '.join(booking.seats)}, name {booking.customer_name}, total {booking.total_price_idr} IDR.",
            tool_call_id=runtime.tool_call_id,
        )
        return Command(update={"draft": CLEARED_AFTER_BOOKING, "messages": [booked, *typed_reply]})

    @tool
    async def list_my_bookings(runtime: Runtime) -> str:
        """The bookings made in this conversation."""
        bookings = await api.bookings_of_session(runtime.context.session_id, runtime.context.caller)
        if not bookings:
            return "No bookings in this conversation yet."
        return json.dumps([booking.model_dump(mode="json") for booking in bookings], ensure_ascii=False)

    return [find_showtimes, get_movie_details, get_seat_map, update_booking, book_tickets, list_my_bookings]

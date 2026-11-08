"""The chat API: what clients send, the server-sent events they get back, and a conversation's view."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.cinema.schemas import Booking


class MessageIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000, description="What the user typed")


class ConfirmationIn(BaseModel):
    approved: bool = Field(description="The user pressed Confirm (true) or Cancel (false)")


class SessionCreated(BaseModel):
    session_id: str


class BookingSummary(BaseModel):
    """Built in code from the database and shown to the user before anything is booked."""

    movie_title: str
    starts_at: datetime
    starts_at_local: str
    studio_number: int
    seats: list[str]
    customer_name: str
    price_per_seat_idr: int
    total_price_idr: int


class ConfirmationAnswer(BaseModel):
    """How a waiting booking is resumed: a button press, or a typed reply the model has read."""

    approved: bool
    # A typed reply goes into the conversation, so the agent can answer it (for example a change of seats)
    user_message: str | None = None


class ChatEvent(BaseModel):
    """One server-sent event of a turn."""

    type: Literal["token", "tool", "confirmation", "booking", "message", "error", "end"]
    text: str | None = None  # token: a piece of the reply, message: the whole reply, error: what went wrong
    name: str | None = None  # tool: the tool the agent is calling
    data: dict[str, Any] | None = None  # confirmation: BookingSummary, booking: Booking, end: token usage


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    text: str


class TokenUsageView(BaseModel):
    used_tokens: int  # model tokens the caller's chat turns used today (UTC), input and output
    daily_tokens: int
    resets_in_seconds: int


class SessionView(BaseModel):
    session_id: str
    turns: list[Turn]
    draft: dict[str, Any]
    pending_confirmation: BookingSummary | None
    bookings: list[Booking]

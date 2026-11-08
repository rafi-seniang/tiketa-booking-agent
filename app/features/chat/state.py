"""What the agent keeps besides the messages (the booking being prepared), and what each turn is given."""

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, NotRequired, TypedDict

from langchain.agents import AgentState


class Draft(TypedDict, total=False):
    """Only update_booking and book_tickets write it, after checking every value against the database."""

    showtime_id: int | None
    # How the prompt shows the chosen showtime, so it needs no query per model call
    showtime_label: str | None
    seats: list[str]
    customer_name: str | None


def merge_draft(current: Draft | None, change: Draft) -> Draft:
    """Tools send only the fields they change, so two tools in one step cannot undo each other."""
    merged: Draft = {**(current or {}), **change}
    return merged


class TiketaState(AgentState):
    draft: NotRequired[Annotated[Draft, merge_draft]]


@dataclass(frozen=True)
class ChatContext:
    """Set by the service for each turn, never by the model: whose conversation it is and the time."""

    session_id: str
    now: datetime


# After a booking the showtime and seats are cleared and the name is kept for the next one
CLEARED_AFTER_BOOKING = Draft(showtime_id=None, showtime_label=None, seats=[])


def missing_fields(draft: Draft) -> list[str]:
    checks = {
        "showtime": draft.get("showtime_id") is not None,
        "seats": bool(draft.get("seats")),
        "name on the booking": bool(draft.get("customer_name")),
    }
    return [field for field, is_present in checks.items() if not is_present]

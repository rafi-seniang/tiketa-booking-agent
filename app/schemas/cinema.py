"""What the cinema hands out and takes in. Seat ids are checked here, once, where they enter."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, Field

from app.utils.seat_layout import AISLE_AFTER_SEAT, ALL_SEAT_IDS, WALKWAY_BEFORE_ROW


def known_seat_id(seat_id: str) -> str:
    if seat_id not in ALL_SEAT_IDS:
        raise ValueError(
            f"{seat_id!r} is not a seat in this studio. Seat ids look like D7: a row letter, then a number"
        )
    return seat_id


def no_repeated_seats(seat_ids: list[str]) -> list[str]:
    if len(set(seat_ids)) != len(seat_ids):
        raise ValueError("a seat is listed twice")
    return seat_ids


SeatId = Annotated[str, AfterValidator(known_seat_id)]
SeatIds = Annotated[list[SeatId], Field(min_length=1), AfterValidator(no_repeated_seats)]
CustomerName = Annotated[str, Field(min_length=1, max_length=80)]


class Movie(BaseModel):
    id: int
    title: str
    synopsis: str
    release_year: int
    genres: list[str]
    studio_number: int
    poster_url: str | None
    trailer_youtube_id: str | None


class Showtime(BaseModel):
    id: int
    movie_id: int
    movie_title: str
    studio_number: int
    starts_at: datetime
    price_idr: int
    seats_left: int


Channel = Literal["chat", "web"]


class Booking(BaseModel):
    code: str
    channel: Channel
    showtime: Showtime
    seats: list[str]
    customer_name: str
    total_price_idr: int
    created_at: datetime


class BookingRequest(BaseModel):
    idempotency_key: str
    owner: str
    channel: Channel
    session_id: str | None = None
    showtime_id: int
    seats: SeatIds
    customer_name: CustomerName


class SeatView(BaseModel):
    id: str
    is_taken: bool


class SeatRowView(BaseModel):
    row: str
    seats: list[SeatView]


class SeatMap(BaseModel):
    """For a UI: rows front to back, and where the aisle and the walkway fall, so a UI draws the real room."""

    showtime: Showtime
    rows: list[SeatRowView]
    aisle_after_seat: int = AISLE_AFTER_SEAT
    walkway_before_row: str = WALKWAY_BEFORE_ROW

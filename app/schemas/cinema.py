"""What the booking API (tiketa-app) answers and takes. That service owns these shapes: the agent only reads them."""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, Field


def no_repeated_seats(seat_ids: list[str]) -> list[str]:
    if len(set(seat_ids)) != len(seat_ids):
        raise ValueError("a seat is listed twice")
    return seat_ids


# Which ids are seats is the booking API's knowledge: the tools check them against its seat map
SeatIds = Annotated[list[str], Field(min_length=1), AfterValidator(no_repeated_seats)]
CustomerName = Annotated[str, Field(min_length=1, max_length=80)]


@dataclass(frozen=True)
class Caller:
    """Who a request is from, as the booking API names them, and the credentials they sent, to pass on as theirs."""

    name: str
    credentials: dict[str, str] = field(repr=False)  # an API key header or the guest cookie: never logged


class Movie(BaseModel):
    id: int
    title: str
    synopsis: str
    release_year: int
    genres: list[str]
    studio_number: int


class Showtime(BaseModel):
    id: int
    movie_id: int
    movie_title: str
    studio_number: int
    starts_at: datetime
    starts_at_local: str
    price_idr: int
    seats_left: int


class Booking(BaseModel):
    code: str
    channel: Literal["web", "chat", "mcp"]
    showtime: Showtime
    seats: list[str]
    customer_name: str
    total_price_idr: int
    created_at: datetime


class SeatView(BaseModel):
    id: str
    is_taken: bool


class SeatRowView(BaseModel):
    row: str
    seats: list[SeatView]


class SeatMap(BaseModel):
    showtime: Showtime
    rows: list[SeatRowView]
    aisle_after_seat: int
    walkway_before_row: str


class Week(BaseModel):
    days: list[date]
    today: date
    is_published: bool


class Cinema(BaseModel):
    name: str
    timezone: str
    max_seats_per_booking: int
    week: Week


class BookingOrder(BaseModel):
    """What the agent sends to book, once the user has said yes."""

    showtime_id: int
    seats: SeatIds
    customer_name: CustomerName
    channel: Literal["chat"] = "chat"
    session_id: str

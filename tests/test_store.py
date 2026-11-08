from datetime import timedelta

import pytest
from pydantic import ValidationError

from app.cinema.schemas import BookingRequest, Showtime
from app.cinema.seat_layout import SEATS_PER_SHOWTIME, seat_map_text
from app.cinema.seed import seed
from app.cinema.store import CinemaStore
from app.platform.database import Sessions
from app.platform.errors import Conflict

from conftest import CINEMA_TIMEZONE, DUNE, NOW


def request(showtime_id: int, seats: list[str], key: str = "call-1", session_id: str = "s1") -> BookingRequest:
    return BookingRequest(
        idempotency_key=key,
        owner="key:key-0001",
        channel="chat",
        session_id=session_id,
        showtime_id=showtime_id,
        seats=seats,
        customer_name="Rafi",
    )


async def test_a_booking_takes_its_seats_and_charges_per_seat(store: CinemaStore, dune_today: list[Showtime]) -> None:
    evening = dune_today[2]
    booking = await store.book(request(evening.id, ["D9", "D10"]), NOW)
    assert booking.seats == ["D9", "D10"]
    assert booking.total_price_idr == 2 * evening.price_idr
    assert await store.taken_seat_ids(evening.id) == {"D9", "D10"}
    assert (await store.get_showtime(evening.id)).seats_left == SEATS_PER_SHOWTIME - 2


async def test_a_seat_is_sold_once_and_a_failed_booking_takes_nothing(
    store: CinemaStore, dune_today: list[Showtime]
) -> None:
    evening = dune_today[2]
    await store.book(request(evening.id, ["D9"], key="first"), NOW)
    with pytest.raises(Conflict, match="D9"):
        await store.book(request(evening.id, ["D10", "D9"], key="second", session_id="s2"), NOW)
    assert await store.taken_seat_ids(evening.id) == {"D9"}  # D10 was not kept from the refused booking


async def test_the_same_tool_call_books_once(store: CinemaStore, dune_today: list[Showtime]) -> None:
    first = await store.book(request(dune_today[2].id, ["E5"]), NOW)
    again = await store.book(request(dune_today[2].id, ["E5"]), NOW)
    assert again.code == first.code
    assert len(await store.bookings_for_session("s1")) == 1


async def test_a_started_showtime_cannot_be_booked(store: CinemaStore, dune_today: list[Showtime]) -> None:
    lunchtime = dune_today[0]
    with pytest.raises(Conflict, match="started"):
        await store.book(request(lunchtime.id, ["A1"]), lunchtime.starts_at + timedelta(minutes=5))


async def test_a_days_showtimes_leave_out_the_ones_already_started(store: CinemaStore) -> None:
    afternoon = NOW + timedelta(hours=6)  # 16:00 in Jakarta
    showtimes = await store.showtimes_on(afternoon.astimezone(CINEMA_TIMEZONE).date(), afternoon, DUNE)
    assert [showtime.starts_at.astimezone(CINEMA_TIMEZONE).strftime("%H:%M") for showtime in showtimes] == [
        "18:00",
        "20:45",
    ]


async def test_seeding_again_adds_nothing(sessions: Sessions) -> None:
    assert await seed(sessions, NOW.astimezone(CINEMA_TIMEZONE).date(), 2, CINEMA_TIMEZONE) == (0, 0)


@pytest.mark.parametrize("seats", [["Z1"], ["d5"], ["K3"], ["D5", "D5"], []])
def test_seats_outside_the_layout_or_repeated_are_refused_where_they_enter(seats: list[str]) -> None:
    with pytest.raises(ValidationError):
        request(1, seats)


def test_the_seat_map_shows_taken_seats_the_aisle_and_the_walkway() -> None:
    lines = seat_map_text({"A9", "M18"}).splitlines()
    assert lines[0] == "SCREEN (front)"
    assert lines[1].startswith("A1 A2") and "A8 -- | A10" in lines[1]
    assert lines[11] == "(walkway)"
    assert lines[-2].endswith("M17 --")

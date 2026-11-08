"""Reads and writes the cinema's tables. A booking is one transaction: all its seats or none of them."""

import secrets
from datetime import date, datetime
from typing import Any, cast
from zoneinfo import ZoneInfo

from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Sessions
from app.core.errors import Conflict, NotFound
from app.models.cinema import BookedSeatRow, BookingRow, MovieRow, ShowtimeRow
from app.schemas.cinema import (
    Booking,
    BookingRequest,
    Channel,
    Movie,
    SeatMap,
    SeatRowView,
    SeatView,
    Showtime,
)
from app.utils.clock import local_day_window
from app.utils.seat_layout import SEATS_PER_SHOWTIME, seat_rows


def new_booking_code() -> str:
    return "TK" + secrets.token_hex(4).upper()


def movie_of(row: MovieRow) -> Movie:
    return Movie.model_validate(row, from_attributes=True)


def showtime_query() -> Select[ShowtimeRow, str, int, Any]:
    """Showtimes with their film and the seats still free, counted from the booked seats."""
    booked = (
        select(BookedSeatRow.showtime_id, func.count().label("booked_seats"))
        .group_by(BookedSeatRow.showtime_id)
        .subquery()
    )
    return (
        select(ShowtimeRow, MovieRow.title, MovieRow.studio_number, func.coalesce(booked.c.booked_seats, 0))
        .join(MovieRow, MovieRow.id == ShowtimeRow.movie_id)
        .outerjoin(booked, booked.c.showtime_id == ShowtimeRow.id)
    )


def showtime_of(row: Any) -> Showtime:
    showtime, title, studio_number, booked_seats = row
    return Showtime(
        id=showtime.id,
        movie_id=showtime.movie_id,
        movie_title=title,
        studio_number=studio_number,
        starts_at=showtime.starts_at,
        price_idr=showtime.price_idr,
        seats_left=SEATS_PER_SHOWTIME - booked_seats,
    )


class CinemaStore:
    def __init__(self, sessions: Sessions, cinema_timezone: ZoneInfo) -> None:
        self._sessions = sessions
        self._cinema_timezone = cinema_timezone

    async def list_movies(self) -> list[Movie]:
        async with self._sessions() as db:
            rows = await db.scalars(select(MovieRow).order_by(MovieRow.studio_number))  # a stable list for the prompt
            return [movie_of(row) for row in rows]

    async def get_movie(self, movie_id: int) -> Movie:
        async with self._sessions() as db:
            row = await db.get(MovieRow, movie_id)
        if row is None:
            raise NotFound(f"There is no film with id {movie_id}")
        return movie_of(row)

    async def showtimes_on(self, day: date, now: datetime, movie_id: int | None) -> list[Showtime]:
        """Showtimes on one cinema-local day that have not started yet, for one film or all of them."""
        day_starts, day_ends = local_day_window(day, self._cinema_timezone)
        query = showtime_query().where(ShowtimeRow.starts_at >= max(day_starts, now), ShowtimeRow.starts_at < day_ends)
        if movie_id is not None:
            query = query.where(ShowtimeRow.movie_id == movie_id)
        async with self._sessions() as db:
            rows = await db.execute(query.order_by(ShowtimeRow.starts_at))  # earliest first, as a schedule reads
            return [showtime_of(row) for row in rows]

    async def get_showtime(self, showtime_id: int) -> Showtime:
        async with self._sessions() as db:
            row = (await db.execute(showtime_query().where(ShowtimeRow.id == showtime_id))).first()
        if row is None:
            raise NotFound(f"There is no showtime with id {showtime_id}")
        return showtime_of(row)

    async def taken_seat_ids(self, showtime_id: int) -> set[str]:
        async with self._sessions() as db:
            seat_ids = await db.scalars(select(BookedSeatRow.seat_id).where(BookedSeatRow.showtime_id == showtime_id))
            return set(seat_ids)

    async def seat_map(self, showtime_id: int) -> SeatMap:
        showtime = await self.get_showtime(showtime_id)
        taken = await self.taken_seat_ids(showtime_id)
        rows = [
            SeatRowView(row=row, seats=[SeatView(id=seat_id, is_taken=seat_id in taken) for seat_id in seat_ids])
            for row, seat_ids in seat_rows()
        ]
        return SeatMap(showtime=showtime, rows=rows)

    async def book(self, request: BookingRequest, now: datetime) -> Booking:
        """Books every seat or none. Called again with the same idempotency key, it returns the first booking."""
        existing = await self._booking_with_key(request.idempotency_key)
        if existing is not None:
            return existing
        try:
            async with self._sessions.begin() as db:
                showtime = await db.get(ShowtimeRow, request.showtime_id)
                if showtime is None:
                    raise NotFound(f"There is no showtime with id {request.showtime_id}")
                if showtime.starts_at <= now:
                    raise Conflict("This showtime has already started")
                booking = BookingRow(
                    code=new_booking_code(),
                    idempotency_key=request.idempotency_key,
                    owner=request.owner,
                    channel=request.channel,
                    session_id=request.session_id,
                    showtime_id=request.showtime_id,
                    customer_name=request.customer_name,
                    total_price_idr=showtime.price_idr * len(request.seats),
                    created_at=now,
                )
                db.add(booking)
                await db.flush()
                db.add_all(
                    BookedSeatRow(booking_id=booking.id, showtime_id=request.showtime_id, seat_id=seat_id)
                    for seat_id in request.seats
                )
        except IntegrityError:
            finished_elsewhere = await self._booking_with_key(request.idempotency_key)
            if finished_elsewhere is not None:
                return finished_elsewhere
            taken = await self.taken_seat_ids(request.showtime_id)
            taken_now = [seat_id for seat_id in request.seats if seat_id in taken]
            raise Conflict(f"Already taken by someone else: {', '.join(taken_now)}") from None
        booked = await self._booking_with_key(request.idempotency_key)
        if booked is None:
            raise RuntimeError("a committed booking could not be read back")
        return booked

    async def bookings_for_session(self, session_id: str) -> list[Booking]:
        async with self._sessions() as db:
            rows = await db.scalars(
                select(BookingRow).where(BookingRow.session_id == session_id).order_by(BookingRow.created_at)
            )  # in the order they were made
            return [await self._booking_of(db, row) for row in rows]  # a conversation has a handful of bookings

    async def bookings_for_owner(self, owner: str, limit: int) -> list[Booking]:
        """The caller's latest bookings, from the chat and the form, newest first."""
        async with self._sessions() as db:
            rows = await db.scalars(
                select(BookingRow)
                .where(BookingRow.owner == owner)
                .order_by(BookingRow.created_at.desc(), BookingRow.id.desc())
                .limit(limit)
            )
            return [await self._booking_of(db, row) for row in rows]

    async def _booking_with_key(self, idempotency_key: str) -> Booking | None:
        async with self._sessions() as db:
            row = await db.scalar(select(BookingRow).where(BookingRow.idempotency_key == idempotency_key))
            return None if row is None else await self._booking_of(db, row)

    async def _booking_of(self, db: AsyncSession, row: BookingRow) -> Booking:
        showtime = showtime_of((await db.execute(showtime_query().where(ShowtimeRow.id == row.showtime_id))).one())
        seat_ids = await db.scalars(
            select(BookedSeatRow.seat_id).where(BookedSeatRow.booking_id == row.id).order_by(BookedSeatRow.id)
        )  # in the order the customer chose them
        return Booking(
            code=row.code,
            channel=cast(Channel, row.channel),
            showtime=showtime,
            seats=list(seat_ids),
            customer_name=row.customer_name,
            total_price_idr=row.total_price_idr,
            created_at=row.created_at,
        )

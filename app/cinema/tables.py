"""The cinema's tables. A seat can be sold once per showtime: the database refuses a second row, not the code."""

from datetime import datetime

from sqlalchemy import JSON, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.database import Base, UtcDateTime


class MovieRow(Base):
    __tablename__ = "movies"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200), unique=True)
    synopsis: Mapped[str] = mapped_column(Text)
    release_year: Mapped[int]
    genres: Mapped[list[str]] = mapped_column(JSON)
    studio_number: Mapped[int] = mapped_column(unique=True)
    poster_url: Mapped[str | None] = mapped_column(String(300))
    trailer_youtube_id: Mapped[str | None] = mapped_column(String(20))


class ShowtimeRow(Base):
    __tablename__ = "showtimes"
    __table_args__ = (UniqueConstraint("movie_id", "starts_at", name="uq_showtime_movie_start"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    movie_id: Mapped[int] = mapped_column(ForeignKey("movies.id"), index=True)
    starts_at: Mapped[datetime] = mapped_column(UtcDateTime, index=True)
    price_idr: Mapped[int]


class BookingRow(Base):
    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(12), unique=True)
    # The agent's tool call id: a retried or resumed call finds its booking instead of making a second one
    idempotency_key: Mapped[str] = mapped_column(String(100), unique=True)
    owner: Mapped[str] = mapped_column(String(80), index=True)  # the caller (API key) the booking belongs to
    channel: Mapped[str] = mapped_column(String(10))  # "chat" (the agent) or "web" (the booking form)
    session_id: Mapped[str | None] = mapped_column(String(40), index=True)  # the conversation, for chat bookings
    showtime_id: Mapped[int] = mapped_column(ForeignKey("showtimes.id"))
    customer_name: Mapped[str] = mapped_column(String(80))
    total_price_idr: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)


class BookedSeatRow(Base):
    __tablename__ = "booked_seats"
    __table_args__ = (UniqueConstraint("showtime_id", "seat_id", name="uq_booked_seat_per_showtime"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id"), index=True)
    showtime_id: Mapped[int] = mapped_column(ForeignKey("showtimes.id"))
    seat_id: Mapped[str] = mapped_column(String(4))

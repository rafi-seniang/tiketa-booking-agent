"""Films, showtimes and bookings now belong to the booking service (tiketa-app). The agent keeps conversations only.

This drops the agent's copies of those tables. Run it on a fresh agent database. To keep bookings made before the
split, keep the old database as it is (or dump it) and point the agent at a new one.

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

UTC_DATETIME = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.drop_table("booked_seats")
    op.drop_table("bookings")
    op.drop_table("showtimes")
    op.drop_table("movies")


def downgrade() -> None:
    op.create_table(
        "movies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(200), nullable=False, unique=True),
        sa.Column("synopsis", sa.Text(), nullable=False),
        sa.Column("release_year", sa.Integer(), nullable=False),
        sa.Column("genres", sa.JSON(), nullable=False),
        sa.Column("studio_number", sa.Integer(), nullable=False, unique=True),
        sa.Column("poster_url", sa.String(300), nullable=True),
        sa.Column("trailer_youtube_id", sa.String(20), nullable=True),
    )
    op.create_table(
        "showtimes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("movie_id", sa.Integer(), sa.ForeignKey("movies.id"), nullable=False),
        sa.Column("starts_at", UTC_DATETIME, nullable=False),
        sa.Column("price_idr", sa.Integer(), nullable=False),
        sa.UniqueConstraint("movie_id", "starts_at", name="uq_showtime_movie_start"),
    )
    op.create_index("ix_showtimes_movie_id", "showtimes", ["movie_id"])
    op.create_index("ix_showtimes_starts_at", "showtimes", ["starts_at"])
    op.create_table(
        "bookings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(12), nullable=False, unique=True),
        sa.Column("idempotency_key", sa.String(100), nullable=False, unique=True),
        sa.Column("owner", sa.String(80), nullable=False),
        sa.Column("channel", sa.String(10), nullable=False),
        sa.Column("session_id", sa.String(40), nullable=True),
        sa.Column("showtime_id", sa.Integer(), sa.ForeignKey("showtimes.id"), nullable=False),
        sa.Column("customer_name", sa.String(80), nullable=False),
        sa.Column("total_price_idr", sa.Integer(), nullable=False),
        sa.Column("created_at", UTC_DATETIME, nullable=False),
    )
    op.create_index("ix_bookings_owner", "bookings", ["owner"])
    op.create_index("ix_bookings_session_id", "bookings", ["session_id"])
    op.create_table(
        "booked_seats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("booking_id", sa.Integer(), sa.ForeignKey("bookings.id"), nullable=False),
        sa.Column("showtime_id", sa.Integer(), sa.ForeignKey("showtimes.id"), nullable=False),
        sa.Column("seat_id", sa.String(4), nullable=False),
        sa.UniqueConstraint("showtime_id", "seat_id", name="uq_booked_seat_per_showtime"),
    )
    op.create_index("ix_booked_seats_booking_id", "booked_seats", ["booking_id"])

"""Bookings belong to a caller and say where they came from, so the booking form can book without a conversation.

Existing bookings all came from the chat: their owner is the owner of their conversation.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("bookings") as table:
        table.add_column(sa.Column("owner", sa.String(80), nullable=True))
        table.add_column(sa.Column("channel", sa.String(10), nullable=True))
    op.execute(
        "UPDATE bookings SET channel = 'chat', "
        "owner = COALESCE((SELECT owner FROM chat_sessions WHERE chat_sessions.id = bookings.session_id), 'unknown')"
    )
    with op.batch_alter_table("bookings") as table:
        table.alter_column("owner", existing_type=sa.String(80), nullable=False)
        table.alter_column("channel", existing_type=sa.String(10), nullable=False)
        table.alter_column("session_id", existing_type=sa.String(40), nullable=True)
        table.create_index("ix_bookings_owner", ["owner"])


def downgrade() -> None:
    op.execute("DELETE FROM booked_seats WHERE booking_id IN (SELECT id FROM bookings WHERE session_id IS NULL)")
    op.execute("DELETE FROM bookings WHERE session_id IS NULL")  # form bookings have no conversation to keep
    with op.batch_alter_table("bookings") as table:
        table.drop_index("ix_bookings_owner")
        table.alter_column("session_id", existing_type=sa.String(40), nullable=False)
        table.drop_column("channel")
        table.drop_column("owner")

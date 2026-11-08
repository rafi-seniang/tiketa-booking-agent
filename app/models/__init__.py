"""SQLAlchemy tables. The schema changes only through Alembic migrations.

Importing this package registers every table on Base.metadata, which Alembic compares against the database.
"""

from app.models import chat, cinema

__all__ = ["chat", "cinema"]

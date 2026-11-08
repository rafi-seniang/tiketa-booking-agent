"""Who owns each conversation. Another caller asking for it gets 404, as if it did not exist."""

import uuid
from datetime import datetime

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, Sessions, UtcDateTime
from app.core.errors import NotFound


class ChatSessionRow(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    owner: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)


class SessionStore:
    def __init__(self, sessions: Sessions) -> None:
        self._sessions = sessions

    async def create(self, owner: str, now: datetime) -> str:
        session_id = uuid.uuid4().hex
        async with self._sessions.begin() as db:
            db.add(ChatSessionRow(id=session_id, owner=owner, created_at=now))
        return session_id

    async def check_owner(self, session_id: str, owner: str) -> None:
        async with self._sessions() as db:
            row = await db.get(ChatSessionRow, session_id)
        if row is None or row.owner != owner:
            raise NotFound(f"There is no conversation {session_id}")

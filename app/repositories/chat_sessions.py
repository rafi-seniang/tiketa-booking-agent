"""Who owns each conversation. Another caller asking for it gets 404, as if it did not exist."""

import uuid
from datetime import datetime

from app.core.database import Sessions
from app.core.errors import NotFound
from app.models.chat import ChatSessionRow


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

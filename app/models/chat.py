"""Who owns each conversation. The conversation itself is a LangGraph checkpoint keyed by the same id."""

from datetime import datetime

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, UtcDateTime


class ChatSessionRow(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    owner: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)

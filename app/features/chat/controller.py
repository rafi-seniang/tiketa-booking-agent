"""Turns chat requests into calls on the service: ownership first, then the turn lock, then the event stream."""

from collections.abc import AsyncIterator
from datetime import datetime

from fastapi.responses import StreamingResponse

from app.features.chat.schemas import (
    ChatEvent,
    ConfirmationIn,
    MessageIn,
    SessionCreated,
    SessionView,
    TokenUsageView,
)
from app.features.chat.service import ChatService


def event_stream(events: AsyncIterator[ChatEvent]) -> StreamingResponse:
    async def encode() -> AsyncIterator[str]:
        async for event in events:
            yield f"data: {event.model_dump_json(exclude_none=True)}\n\n"

    # no-cache and no proxy buffering, so each token reaches the browser as it is written
    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    return StreamingResponse(encode(), media_type="text/event-stream", headers=headers)


class ChatController:
    def __init__(self, service: ChatService) -> None:
        self._service = service

    async def start(self, owner: str, now: datetime) -> SessionCreated:
        return SessionCreated(session_id=await self._service.start_session(owner, now))

    async def view(self, session_id: str, owner: str) -> SessionView:
        await self._service.check_owner(session_id, owner)
        return await self._service.view(session_id)

    async def send_message(self, session_id: str, body: MessageIn, owner: str, now: datetime) -> StreamingResponse:
        await self._service.check_owner(session_id, owner)  # 404 and 409 go out before the stream starts
        await self._service.begin_turn(session_id, owner)
        return event_stream(self._service.message_turn(session_id, owner, body.message, now))

    async def answer_confirmation(
        self, session_id: str, body: ConfirmationIn, owner: str, now: datetime
    ) -> StreamingResponse:
        await self._service.check_owner(session_id, owner)
        await self._service.begin_turn(session_id, owner, answers_confirmation=True)
        return event_stream(self._service.confirmation_turn(session_id, owner, body.approved, now))

    async def token_usage(self, owner: str) -> TokenUsageView:
        return await self._service.token_usage(owner)

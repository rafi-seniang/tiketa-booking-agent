"""Conversations: start one, read it back, send a message, answer a booking's confirmation. Replies stream as SSE."""

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.controllers.chat import ChatController
from app.core.dependencies import get_chat_controller, get_now
from app.middleware.rate_limit import caller_of
from app.schemas.chat import ConfirmationIn, MessageIn, SessionCreated, SessionView, TokenUsageView

router = APIRouter(prefix="/sessions", tags=["chat"])
usage_router = APIRouter(tags=["chat"])
Controller = Annotated[ChatController, Depends(get_chat_controller)]
Caller = Annotated[str, Depends(caller_of)]
Now = Annotated[datetime, Depends(get_now)]
EVENT_STREAM: dict[int | str, dict[str, Any]] = {
    200: {"content": {"text/event-stream": {}}, "description": "ChatEvent objects, one per data: line"}
}


@router.post("", status_code=201)
async def start_session(controller: Controller, caller: Caller, now: Now) -> SessionCreated:
    return await controller.start(caller, now)


@router.get("/{session_id}")
async def get_session(session_id: UUID, controller: Controller, caller: Caller) -> SessionView:
    return await controller.view(session_id.hex, caller)


@router.post("/{session_id}/messages", response_class=StreamingResponse, responses=EVENT_STREAM)
async def send_message(
    session_id: UUID, body: MessageIn, controller: Controller, caller: Caller, now: Now
) -> StreamingResponse:
    return await controller.send_message(session_id.hex, body, caller, now)


@router.post("/{session_id}/confirmation", response_class=StreamingResponse, responses=EVENT_STREAM)
async def answer_confirmation(
    session_id: UUID, body: ConfirmationIn, controller: Controller, caller: Caller, now: Now
) -> StreamingResponse:
    return await controller.answer_confirmation(session_id.hex, body, caller, now)


@usage_router.get("/usage")
async def token_usage(controller: Controller, caller: Caller) -> TokenUsageView:
    """The caller's model tokens today against the daily budget. The booking form spends none."""
    return await controller.token_usage(caller)

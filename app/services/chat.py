"""One chat turn: run or resume the agent and turn what it does into events. The conversation lives in the
checkpointer, keyed by session id, so any worker can take the next turn."""

import logging
import time
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command, StateSnapshot, StreamMode, StreamPart

from app.core.errors import Conflict, RateLimited
from app.core.locks import KeyLock
from app.core.token_budget import EVERYONE, TokenBudget, seconds_to_reset
from app.generative.confirmation import ConfirmationReader
from app.repositories.chat_sessions import SessionStore
from app.repositories.cinema import CinemaStore
from app.schemas.agent import ChatContext
from app.schemas.chat import BookingSummary, ChatEvent, SessionView, TokenUsageView, Turn

logger = logging.getLogger(__name__)

STREAM_MODES: list[StreamMode] = ["messages", "updates", "custom"]
FAILED_TURN_TEXT = "The assistant could not finish this reply. Please try again."


def is_summary(message: BaseMessage) -> bool:
    return message.additional_kwargs.get("lc_source") == "summarization"


def turns_of(messages: list[BaseMessage]) -> list[Turn]:
    """What the user and the assistant said, without tool traffic or the summary of older messages."""
    turns: list[Turn] = []
    for message in messages:  # in conversation order
        if isinstance(message, HumanMessage) and not is_summary(message):
            turns.append(Turn(role="user", text=message.text))
        elif isinstance(message, AIMessage) and message.text:
            turns.append(Turn(role="assistant", text=message.text))
    return turns


class TurnUsage:
    def __init__(self) -> None:
        self.model_calls = 0
        self.input_tokens = 0
        self.cached_input_tokens = 0  # read from the provider's prompt cache, billed at a lower rate
        self.output_tokens = 0

    def add(self, message: AIMessage) -> None:
        self.model_calls += 1
        if message.usage_metadata is not None:
            self.input_tokens += message.usage_metadata["input_tokens"]
            self.cached_input_tokens += message.usage_metadata.get("input_token_details", {}).get("cache_read") or 0
            self.output_tokens += message.usage_metadata["output_tokens"]

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def as_data(self) -> dict[str, int]:
        return {
            "model_calls": self.model_calls,
            "input_tokens": self.input_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "output_tokens": self.output_tokens,
        }


def events_of(part: StreamPart[Any, Any], usage: TurnUsage) -> list[ChatEvent]:
    if part["type"] == "messages":
        message, metadata = part["data"]
        is_reply_text = metadata.get("langgraph_node") == "model" and isinstance(message, AIMessageChunk)
        return [ChatEvent(type="token", text=message.text)] if is_reply_text and message.text else []
    if part["type"] == "custom":
        return [ChatEvent(type="booking", data=part["data"]["booking"])]
    if part["type"] != "updates":
        return []
    events: list[ChatEvent] = []
    for waiting in part["data"].get("__interrupt__", ()):
        events.append(ChatEvent(type="confirmation", data=waiting.value["summary"]))
    model_update = part["data"].get("model") or {}
    for message in model_update.get("messages", []):  # one reply per model call
        usage.add(message)
        if message.tool_calls:
            events.extend(ChatEvent(type="tool", name=call["name"]) for call in message.tool_calls)
        elif message.text:
            events.append(ChatEvent(type="message", text=message.text))
    return events


class ChatService:
    def __init__(
        self,
        agent: CompiledStateGraph[Any, Any, Any, Any],
        reader: ConfirmationReader,
        sessions: SessionStore,
        store: CinemaStore,
        lock: KeyLock,
        turn_lock_seconds: int,
        budget: TokenBudget,
        daily_tokens: int,
        daily_tokens_total: int,
    ) -> None:
        self._agent = agent
        self._reader = reader
        self._sessions = sessions
        self._store = store
        self._lock = lock
        self._turn_lock_seconds = turn_lock_seconds
        self._budget = budget
        self._daily_tokens = daily_tokens
        self._daily_tokens_total = daily_tokens_total

    async def start_session(self, owner: str, now: datetime) -> str:
        return await self._sessions.create(owner, now)

    async def check_owner(self, session_id: str, owner: str) -> None:
        await self._sessions.check_owner(session_id, owner)

    async def view(self, session_id: str) -> SessionView:
        snapshot = await self._agent.aget_state(config_of(session_id))
        return SessionView(
            session_id=session_id,
            turns=turns_of(snapshot.values.get("messages", [])),
            draft=dict(snapshot.values.get("draft", {})),
            pending_confirmation=pending_in(snapshot),
            bookings=await self._store.bookings_for_session(session_id),
        )

    async def pending_confirmation(self, session_id: str) -> BookingSummary | None:
        return pending_in(await self._agent.aget_state(config_of(session_id)))

    async def token_usage(self, owner: str) -> TokenUsageView:
        return TokenUsageView(
            used_tokens=await self._budget.used(owner),
            daily_tokens=self._daily_tokens,
            resets_in_seconds=seconds_to_reset(time.time()),
        )

    async def begin_turn(self, session_id: str, owner: str, answers_confirmation: bool = False) -> None:
        """One turn at a time per conversation, within the day's tokens for everyone and for the caller."""
        if await self._budget.used(EVERYONE) >= self._daily_tokens_total:
            reset = seconds_to_reset(time.time())
            raise RateLimited(
                "The chat is closed for today: its model budget is used up. The booking form still works", reset
            )
        if await self._budget.used(owner) >= self._daily_tokens:
            reset = seconds_to_reset(time.time())
            raise RateLimited(f"The {self._daily_tokens:,} model tokens for today are used up", reset)
        if not await self._lock.acquire(f"turn:{session_id}", self._turn_lock_seconds):
            raise Conflict("This conversation is still answering the previous message")
        if answers_confirmation and await self.pending_confirmation(session_id) is None:
            await self._lock.release(f"turn:{session_id}")
            raise Conflict("No booking is waiting for confirmation")

    async def message_turn(self, session_id: str, owner: str, text: str, now: datetime) -> AsyncIterator[ChatEvent]:
        """The caller has begun the turn. It ends here, whatever happens."""
        try:
            try:
                graph_input = await self._input_for(session_id, text)
            except Exception:  # the response has started, so the failure travels as an event
                logger.exception("chat turn failed to start", extra={"extra_fields": {"session_id": session_id}})
                yield ChatEvent(type="error", text=FAILED_TURN_TEXT)
                yield ChatEvent(type="end", data=TurnUsage().as_data())
                return
            async for event in self._run(graph_input, session_id, owner, now):
                yield event
        finally:
            await self._lock.release(f"turn:{session_id}")

    async def _input_for(self, session_id: str, text: str) -> Any:
        """A new message, or the answer to the booking waiting for one, as the model reads the typed reply."""
        pending = await self.pending_confirmation(session_id)
        if pending is not None:
            approved = await self._reader.approves(pending, text)
            return Command(resume={"approved": approved, "user_message": text})
        await self._close_unfinished_tool_calls(session_id)
        return {"messages": [HumanMessage(text)]}

    async def confirmation_turn(
        self, session_id: str, owner: str, approved: bool, now: datetime
    ) -> AsyncIterator[ChatEvent]:
        """A Confirm or Cancel button press. The caller has begun the turn. It ends here, whatever happens."""
        try:
            async for event in self._run(Command(resume={"approved": approved}), session_id, owner, now):
                yield event
        finally:
            await self._lock.release(f"turn:{session_id}")

    async def _run(self, graph_input: Any, session_id: str, owner: str, now: datetime) -> AsyncIterator[ChatEvent]:
        usage = TurnUsage()
        try:
            async for part in self._agent.astream(
                graph_input,
                config_of(session_id),
                context=ChatContext(session_id=session_id, owner=owner, now=now),
                stream_mode=STREAM_MODES,
                version="v2",
            ):
                for event in events_of(part, usage):
                    yield event
        except Exception:  # the response has started, so the failure travels as an event
            logger.exception("chat turn failed", extra={"extra_fields": {"session_id": session_id}})
            yield ChatEvent(type="error", text=FAILED_TURN_TEXT)
        finally:  # a failed or abandoned turn still spent what it used
            await self._budget.add(owner, usage.total_tokens)
        yield ChatEvent(type="end", data=usage.as_data())

    async def _close_unfinished_tool_calls(self, session_id: str) -> None:
        """After a turn failed inside a tool, answer its calls as not run, or the model provider refuses the history."""
        config = config_of(session_id)
        snapshot = await self._agent.aget_state(config)
        messages = snapshot.values.get("messages", [])
        if not snapshot.next or not messages or not isinstance(messages[-1], AIMessage):
            return
        answered = {message.tool_call_id for message in messages if isinstance(message, ToolMessage)}
        not_run = [
            ToolMessage("Not run: the previous turn failed.", tool_call_id=call["id"], status="error")
            for call in messages[-1].tool_calls
            if call["id"] not in answered
        ]
        if not_run:
            await self._agent.aupdate_state(config, {"messages": not_run}, as_node="tools")


def config_of(session_id: str) -> RunnableConfig:
    return {"configurable": {"thread_id": session_id}}


def pending_in(snapshot: StateSnapshot) -> BookingSummary | None:
    """The booking waiting for the user's answer, if the conversation is paused on one."""
    if not snapshot.interrupts:
        return None
    return BookingSummary.model_validate(snapshot.interrupts[0].value["summary"])

"""The booking agent: LangChain's agent loop on LangGraph, with the prompt, limits and summaries as middleware."""

from collections.abc import Awaitable, Callable
from typing import Any, cast
from zoneinfo import ZoneInfo

from langchain.agents import create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    ModelCallLimitMiddleware,
    ModelRequest,
    ModelResponse,
    ModelRetryMiddleware,
    SummarizationMiddleware,
    ToolCallRequest,
    wrap_model_call,
    wrap_tool_call,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage, ToolMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from app.core.errors import Conflict, NotFound
from app.engines.llm import STREAM_DROPPED_ERRORS
from app.generative.prompts import system_prompt, turn_context
from app.repositories.cinema import CinemaStore
from app.schemas.agent import ChatContext, Draft, TiketaState
from app.schemas.cinema import Movie
from app.settings import Settings
from app.tools.booking import build_tools


@wrap_tool_call
async def report_refusals(
    request: ToolCallRequest, handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]]
) -> ToolMessage | Command[Any]:
    """A refused change goes back to the model as text it can act on. Infrastructure errors still fail the turn."""
    try:
        return await handler(request)
    except (NotFound, Conflict) as refusal:
        return ToolMessage(f"Not done: {refusal.detail}", tool_call_id=request.tool_call["id"], status="error")


def build_agent(
    model: BaseChatModel,
    store: CinemaStore,
    movies: list[Movie],
    settings: Settings,
    cinema_timezone: ZoneInfo,
    checkpointer: BaseCheckpointSaver[Any],
) -> CompiledStateGraph[Any, Any, Any, Any]:
    @wrap_model_call
    async def add_turn_context(
        request: ModelRequest[ChatContext], handler: Callable[[ModelRequest[ChatContext]], Awaitable[ModelResponse]]
    ) -> ModelResponse:
        """The time and the draft go after the conversation, for this call only. They are not saved in the state."""
        state = cast(TiketaState, request.state)  # the agent runs with state_schema=TiketaState
        context = turn_context(state.get("draft") or Draft(), request.runtime.context.now, cinema_timezone)
        return await handler(request.override(messages=[*request.messages, SystemMessage(context)]))

    middleware: list[AgentMiddleware[Any, Any, Any]] = [
        SummarizationMiddleware(
            model,
            trigger=("tokens", settings.summarize_from_tokens),
            keep=("messages", settings.messages_kept_after_summary),
        ),
        ModelCallLimitMiddleware(run_limit=settings.max_model_calls_per_turn, exit_behavior="error"),
        add_turn_context,
        # One more try when the provider drops a stream half way. A second failure fails the turn
        ModelRetryMiddleware(max_retries=1, retry_on=STREAM_DROPPED_ERRORS, on_failure="error"),
        report_refusals,
    ]
    return create_agent(
        model=model,
        system_prompt=system_prompt(movies, settings.cinema_name, settings.max_seats_per_booking),
        tools=build_tools(store, cinema_timezone, settings.max_seats_per_booking),
        middleware=middleware,
        state_schema=TiketaState,
        context_schema=ChatContext,
        checkpointer=checkpointer,
        name="tiketa",
    )

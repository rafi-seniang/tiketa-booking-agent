"""The booking agent: LangChain's agent loop on LangGraph, with the prompt, limits and summaries as middleware."""

from collections.abc import Awaitable, Callable
from typing import Any, cast
from zoneinfo import ZoneInfo

from langchain.agents import create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    ModelCallLimitMiddleware,
    ModelRequest,
    ModelRetryMiddleware,
    SummarizationMiddleware,
    ToolCallRequest,
    dynamic_prompt,
    wrap_tool_call,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import ToolMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from app.cinema.schemas import Movie
from app.cinema.store import CinemaStore
from app.engines.llm import STREAM_DROPPED_ERRORS
from app.features.chat.prompt import movie_lines, system_prompt
from app.features.chat.state import ChatContext, Draft, TiketaState
from app.features.chat.tools import build_tools
from app.platform.errors import Conflict, NotFound
from config.settings import Settings


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
    movies_text = movie_lines(movies)  # the films are loaded once at startup

    @dynamic_prompt
    def tiketa_prompt(request: ModelRequest[ChatContext]) -> str:
        state = cast(TiketaState, request.state)  # the agent runs with state_schema=TiketaState
        return system_prompt(
            movies_text,
            state.get("draft") or Draft(),
            request.runtime.context.now,
            settings.cinema_name,
            cinema_timezone,
            settings.max_seats_per_booking,
        )

    middleware: list[AgentMiddleware[Any, Any, Any]] = [
        SummarizationMiddleware(
            model,
            trigger=("tokens", settings.summarize_from_tokens),
            keep=("messages", settings.messages_kept_after_summary),
        ),
        ModelCallLimitMiddleware(run_limit=settings.max_model_calls_per_turn, exit_behavior="error"),
        tiketa_prompt,
        # One more try when the provider drops a stream half way. A second failure fails the turn
        ModelRetryMiddleware(max_retries=1, retry_on=STREAM_DROPPED_ERRORS, on_failure="error"),
        report_refusals,
    ]
    return create_agent(
        model=model,
        tools=build_tools(store, cinema_timezone, settings.max_seats_per_booking),
        middleware=middleware,
        state_schema=TiketaState,
        context_schema=ChatContext,
        checkpointer=checkpointer,
        name="tiketa",
    )

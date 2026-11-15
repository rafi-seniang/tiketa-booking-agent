"""Everything long-lived, built once at startup and closed on shutdown: the booking API client, the database of
conversations, the checkpointer, Redis, the agent."""

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from dataclasses import dataclass

import httpx
from fastapi import FastAPI

from app.core.checkpoints import open_checkpointer
from app.core.database import connect_database
from app.core.locks import InMemoryKeyLock, KeyLock, RedisKeyLock
from app.core.migrations import check_schema
from app.core.redis import connect_redis
from app.core.token_budget import InMemoryTokenBudget, RedisTokenBudget, TokenBudget
from app.core.tracing import start_tracing
from app.engines.llm import build_agent_model
from app.generative.confirmation import ConfirmationReader
from app.middleware.rate_limit import InMemoryRateLimiter, RateLimiter, RedisRateLimiter
from app.repositories.booking_api import BookingApi
from app.repositories.chat_sessions import SessionStore
from app.schemas.cinema import Caller
from app.services.booking_agent import build_agent
from app.services.chat import ChatService
from app.settings import Settings


@dataclass
class Resources:
    chat: ChatService
    api: BookingApi
    rate_limiter: RateLimiter
    model_name: str


def service_caller(settings: Settings) -> Caller:
    """The agent itself, for the two reads at startup that happen before any user is there."""
    key = settings.booking_api_key.get_secret_value()
    return Caller(name="agent", credentials={"X-API-Key": key} if key else {})


@asynccontextmanager
async def open_resources(settings: Settings) -> AsyncIterator[Resources]:
    async with AsyncExitStack() as stack:  # closes in reverse order, also when startup fails half way
        stop_tracing = start_tracing(settings)  # before the model is built, so its calls are traced
        if stop_tracing is not None:
            stack.callback(stop_tracing)
        http = await stack.enter_async_context(
            httpx.AsyncClient(base_url=settings.booking_api_url, timeout=settings.booking_api_timeout_seconds)
        )
        api = BookingApi(http)
        # The agent is an add-on to the booking service. Without it there is nothing to book, so it does not start
        cinema = await api.cinema(service_caller(settings))
        movies = await api.list_movies(service_caller(settings))
        database_url = settings.database_url.get_secret_value()
        engine, sessions = connect_database(database_url)
        stack.push_async_callback(engine.dispose)
        await check_schema(engine)  # migrations run before the service, not inside it
        checkpointer = await stack.enter_async_context(open_checkpointer(database_url))
        redis = await connect_redis(settings)
        if redis is not None:
            stack.push_async_callback(redis.aclose)
        rate_limiter: RateLimiter = RedisRateLimiter(redis) if redis is not None else InMemoryRateLimiter()
        lock: KeyLock = RedisKeyLock(redis) if redis is not None else InMemoryKeyLock()
        budget: TokenBudget = RedisTokenBudget(redis) if redis is not None else InMemoryTokenBudget()
        model = build_agent_model(settings)
        agent = build_agent(model, api, movies, cinema, settings, checkpointer)
        # A yes or no needs no thinking, and DeepSeek refuses the reader's forced tool call in thinking mode
        reader = ConfirmationReader(build_agent_model(settings, reasoning_effort="none"))
        chat = ChatService(
            agent,
            reader,
            SessionStore(sessions),
            api,
            lock,
            settings.turn_lock_seconds,
            budget,
            settings.daily_tokens_per_caller,
            settings.daily_tokens_total,
        )
        yield Resources(chat=chat, api=api, rate_limiter=rate_limiter, model_name=settings.llm_model)


def lifespan(settings: Settings) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    @asynccontextmanager
    async def run(app: FastAPI) -> AsyncIterator[None]:
        async with open_resources(settings) as resources:  # everything loads here, before any request
            app.state.resources = resources
            yield

    return run

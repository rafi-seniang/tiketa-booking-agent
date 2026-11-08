"""Everything long-lived, built once at startup and closed on shutdown: database, checkpointer, Redis, the agent."""

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from fastapi import FastAPI

from app.cinema.store import CinemaStore
from app.engines.llm import build_chat_model
from app.features.chat.agent import build_agent
from app.features.chat.confirmation import ConfirmationReader
from app.features.chat.service import ChatService
from app.features.chat.session_store import SessionStore
from app.platform.checkpoints import open_checkpointer
from app.platform.database import connect_database
from app.platform.locks import InMemoryKeyLock, KeyLock, RedisKeyLock
from app.platform.migrations import check_schema
from app.platform.rate_limit import InMemoryRateLimiter, RateLimiter, RedisRateLimiter
from app.platform.redis import connect_redis
from app.platform.tracing import start_tracing
from config.settings import Settings


@dataclass
class Resources:
    chat: ChatService
    store: CinemaStore
    rate_limiter: RateLimiter
    model_name: str


@asynccontextmanager
async def open_resources(settings: Settings) -> AsyncIterator[Resources]:
    async with AsyncExitStack() as stack:  # closes in reverse order, also when startup fails half way
        stop_tracing = start_tracing(settings)  # before the model is built, so its calls are traced
        if stop_tracing is not None:
            stack.callback(stop_tracing)
        database_url = settings.database_url.get_secret_value()
        engine, sessions = connect_database(database_url)
        stack.push_async_callback(engine.dispose)
        await check_schema(engine)  # migrations run before the service, not inside it
        cinema_timezone = ZoneInfo(settings.cinema_timezone)
        store = CinemaStore(sessions, cinema_timezone)
        movies = await store.list_movies()
        if not movies:
            raise RuntimeError("The cinema has no films yet: run `python scripts/seed.py` first")
        checkpointer = await stack.enter_async_context(open_checkpointer(database_url))
        redis = await connect_redis(settings)
        if redis is not None:
            stack.push_async_callback(redis.aclose)
        rate_limiter: RateLimiter = RedisRateLimiter(redis) if redis is not None else InMemoryRateLimiter()
        lock: KeyLock = RedisKeyLock(redis) if redis is not None else InMemoryKeyLock()
        model = build_chat_model(settings.llm_model, settings)
        agent = build_agent(model, store, movies, settings, cinema_timezone, checkpointer)
        # A yes or no needs no thinking, and DeepSeek refuses the reader's forced tool call in thinking mode
        reader = ConfirmationReader(build_chat_model(settings.llm_model, settings, reasoning_effort="none"))
        chat = ChatService(agent, reader, SessionStore(sessions), store, lock, settings.turn_lock_seconds)
        yield Resources(chat=chat, store=store, rate_limiter=rate_limiter, model_name=settings.llm_model)


def lifespan(settings: Settings) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    @asynccontextmanager
    async def run(app: FastAPI) -> AsyncIterator[None]:
        async with open_resources(settings) as resources:  # everything loads here, before any request
            app.state.resources = resources
            yield

    return run

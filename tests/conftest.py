import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph.state import CompiledStateGraph

from app.bootstrap import create_app
from app.cinema.schemas import Showtime
from app.cinema.seed import seed
from app.cinema.store import CinemaStore
from app.features.chat.agent import build_agent
from app.features.chat.schemas import BookingSummary
from app.features.chat.service import ChatService
from app.features.chat.session_store import SessionStore
from app.platform.database import Base, Sessions, connect_database
from app.platform.dependencies import get_now, get_resources
from app.platform.locks import InMemoryKeyLock
from app.platform.rate_limit import InMemoryRateLimiter
from app.platform.resources import Resources
from config.settings import Settings

from fakes import ScriptedChatModel

CINEMA_TIMEZONE = ZoneInfo("Asia/Jakarta")
NOW = datetime(2026, 11, 8, 3, 0, tzinfo=UTC)  # Sunday 10:00 in Jakarta
DUNE = 9  # the film id of Dune: Part Two in the seed, shown at 12:30, 15:15, 18:00 and 20:45


class FakeReader:
    """Stands in for the model that reads a typed reply to a waiting booking."""

    def __init__(self) -> None:
        self.approve = False
        self.replies_read: list[str] = []

    async def approves(self, summary: BookingSummary, reply: str) -> bool:
        self.replies_read.append(reply)
        return self.approve


def parse_events(body: str) -> list[dict[str, Any]]:
    return [json.loads(line[len("data: ") :]) for line in body.splitlines() if line.startswith("data: ")]


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """A test module can override this fixture to change a setting."""
    return Settings(  # type: ignore[call-arg]
        _env_file=None,
        environment="test",
        api_keys="test-key-0001,other-key-0002",
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'tiketa.db').as_posix()}",
    )


@pytest.fixture
async def sessions(settings: Settings) -> AsyncIterator[Sessions]:
    engine, session_factory = connect_database(settings.database_url.get_secret_value())
    async with engine.begin() as connection:  # migrations are tested on their own in test_migrations.py
        await connection.run_sync(Base.metadata.create_all)
    await seed(session_factory, NOW.astimezone(CINEMA_TIMEZONE).date(), 2, CINEMA_TIMEZONE)
    yield session_factory
    await engine.dispose()


@pytest.fixture
def store(sessions: Sessions) -> CinemaStore:
    return CinemaStore(sessions, CINEMA_TIMEZONE)


@pytest.fixture
async def dune_today(store: CinemaStore) -> list[Showtime]:
    return await store.showtimes_on(NOW.astimezone(CINEMA_TIMEZONE).date(), NOW, DUNE)


@pytest.fixture
def model() -> ScriptedChatModel:
    return ScriptedChatModel(replies=[])


@pytest.fixture
async def agent(
    model: ScriptedChatModel, store: CinemaStore, settings: Settings
) -> CompiledStateGraph[Any, Any, Any, Any]:
    return build_agent(model, store, await store.list_movies(), settings, CINEMA_TIMEZONE, InMemorySaver())


@pytest.fixture
def reader() -> FakeReader:
    return FakeReader()


@pytest.fixture
def chat(
    agent: CompiledStateGraph[Any, Any, Any, Any], reader: FakeReader, sessions: Sessions, store: CinemaStore
) -> ChatService:
    return ChatService(agent, reader, SessionStore(sessions), store, InMemoryKeyLock(), 60)  # type: ignore[arg-type]


@pytest.fixture
async def client(settings: Settings, chat: ChatService, store: CinemaStore) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings)
    resources = Resources(chat=chat, store=store, rate_limiter=InMemoryRateLimiter(), model_name="scripted")
    app.dependency_overrides[get_resources] = lambda: resources
    app.dependency_overrides[get_now] = lambda: NOW
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", headers={"X-API-Key": "test-key-0001"}
    ) as http:
        yield http

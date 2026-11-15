import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph.state import CompiledStateGraph

from app.core.application import create_app
from app.core.database import Base, Sessions, connect_database
from app.core.dependencies import get_now, get_resources
from app.core.lifespan import Resources
from app.core.locks import InMemoryKeyLock
from app.core.token_budget import InMemoryTokenBudget
from app.middleware.rate_limit import InMemoryRateLimiter
from app.repositories.chat_sessions import SessionStore
from app.schemas.chat import BookingSummary
from app.schemas.cinema import Caller, Showtime
from app.services.booking_agent import build_agent
from app.services.chat import ChatService
from app.settings import Settings

from fakes import FakeBookingApi, ScriptedChatModel

NOW = datetime(2026, 11, 8, 3, 0, tzinfo=UTC)  # Sunday 10:00 in Jakarta
API_KEY = "test-key-0001"
OWNER = f"key:{API_KEY}"  # how the fake booking API names the test client's caller
CALLER = Caller(name=OWNER, credentials={"X-API-Key": API_KEY})


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
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'agent.db').as_posix()}",
    )


@pytest.fixture
async def sessions(settings: Settings) -> AsyncIterator[Sessions]:
    engine, session_factory = connect_database(settings.database_url.get_secret_value())
    async with engine.begin() as connection:  # migrations are tested on their own in test_migrations.py
        await connection.run_sync(Base.metadata.create_all)
    yield session_factory
    await engine.dispose()


@pytest.fixture
def api() -> FakeBookingApi:
    """The booking service the agent books through, in memory."""
    return FakeBookingApi(NOW)


@pytest.fixture
def dune_today(api: FakeBookingApi) -> list[Showtime]:
    return api.showtimes  # Dune at 12:00, 15:00, 18:00 and 21:00 today


@pytest.fixture
def model() -> ScriptedChatModel:
    return ScriptedChatModel(replies=[])


@pytest.fixture
async def agent(
    model: ScriptedChatModel, api: FakeBookingApi, settings: Settings
) -> CompiledStateGraph[Any, Any, Any, Any]:
    api_any: Any = api  # FakeBookingApi has the client's methods
    return build_agent(
        model, api_any, await api.list_movies(CALLER), await api.cinema(CALLER), settings, InMemorySaver()
    )


@pytest.fixture
def reader() -> FakeReader:
    return FakeReader()


@pytest.fixture
def budget() -> InMemoryTokenBudget:
    return InMemoryTokenBudget()


@pytest.fixture
def chat(
    agent: CompiledStateGraph[Any, Any, Any, Any],
    reader: FakeReader,
    sessions: Sessions,
    api: FakeBookingApi,
    budget: InMemoryTokenBudget,
) -> ChatService:
    reader_any: Any = reader  # FakeReader has the reader's one method
    api_any: Any = api
    return ChatService(
        agent, reader_any, SessionStore(sessions), api_any, InMemoryKeyLock(), 60, budget, 10_000, 50_000
    )


@pytest.fixture
async def client(settings: Settings, chat: ChatService, api: FakeBookingApi) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings)
    api_any: Any = api
    resources = Resources(chat=chat, api=api_any, rate_limiter=InMemoryRateLimiter(), model_name="scripted")
    app.dependency_overrides[get_resources] = lambda: resources
    app.dependency_overrides[get_now] = lambda: NOW
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers={"X-API-Key": API_KEY}) as http:
        yield http

import httpx
import pytest

from app.middleware import rate_limit
from app.settings import Settings


@pytest.fixture
def settings(settings: Settings) -> Settings:
    return settings.model_copy(update={"rate_limit_per_minute": 2})


async def test_a_caller_over_the_limit_gets_429_with_retry_after(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rate_limit.time, "time", lambda: 1_000_040.0)  # 20 seconds into a minute, 40 before its end
    statuses = [(await client.get("/v1/movies")).status_code for _ in range(3)]
    assert statuses == [200, 200, 429]
    assert (await client.get("/v1/movies")).headers["Retry-After"] == "40"

"""A browser books with a guest session cookie instead of an API key, and only sees its own bookings."""

import time

import httpx
import pytest

from app.middleware import auth
from app.middleware.auth import GUEST_COOKIE, GuestSessions
from app.schemas.cinema import Showtime
from app.settings import Settings


def guest_client(client: httpx.AsyncClient) -> httpx.AsyncClient:
    """A second client on the same app, without the API key, like a browser."""
    return httpx.AsyncClient(transport=client._transport, base_url="http://test")


def seat_on_form(showtime: Showtime, seat: str) -> dict[str, object]:
    return {"showtime_id": showtime.id, "seats": [seat], "customer_name": "Sari"}


async def test_a_browser_books_with_a_guest_cookie_and_sees_only_its_own(
    client: httpx.AsyncClient, dune_today: list[Showtime]
) -> None:
    async with guest_client(client) as first, guest_client(client) as second:
        assert (await first.get("/v1/movies")).status_code == 401
        started = await first.post("/auth/guest")
        assert started.status_code == 204
        cookie = started.headers["set-cookie"]
        assert "HttpOnly" in cookie and "SameSite=strict" in cookie
        await second.post("/auth/guest")

        booked = await first.post(
            "/v1/bookings", json=seat_on_form(dune_today[2], "C3"), headers={"Idempotency-Key": "browser-key-1"}
        )
        assert booked.status_code == 201
        assert [b["code"] for b in (await first.get("/v1/bookings")).json()] == [booked.json()["code"]]
        assert (await second.get("/v1/bookings")).json() == []
        assert (await client.get("/v1/bookings")).json() == []  # the API key is a third caller


async def test_a_changed_or_expired_cookie_is_refused(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with guest_client(client) as browser:
        await browser.post("/auth/guest")
        token = browser.cookies[GUEST_COOKIE]
        _, expires, signature = token.split(".")
        browser.cookies.set(GUEST_COOKIE, f"someone-else.{expires}.{signature}")
        assert (await browser.get("/v1/movies")).status_code == 401
        browser.cookies.set(GUEST_COOKIE, GuestSessions("another-secret", 7).issue())
        assert (await browser.get("/v1/movies")).status_code == 401

        browser.cookies.set(GUEST_COOKIE, token)
        assert (await browser.get("/v1/movies")).status_code == 200
        eight_days_later = time.time() + 8 * 86_400
        monkeypatch.setattr(auth.time, "time", lambda: eight_days_later)
        assert (await browser.get("/v1/movies")).status_code == 401


def test_production_refuses_to_start_without_its_secrets() -> None:
    with pytest.raises(ValueError, match="SESSION_SECRET"):
        Settings(_env_file=None, environment="production", database_url="sqlite+aiosqlite://", api_keys="k")  # type: ignore[call-arg]

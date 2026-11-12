"""The agent's client of the booking service: what it sends, and how it reads a refusal."""

import json
from datetime import date
from typing import Any

import httpx
import pytest
from fastapi import Request

from app.core.errors import BookingApiUnavailable, Conflict, NotFound, RateLimited, Unauthorized
from app.middleware.auth import credentials_of
from app.repositories.booking_api import BookingApi, idempotency_key_of
from app.schemas.cinema import BookingOrder, Caller
from app.settings import Settings

GUEST = Caller(name="guest:abc", credentials={"Cookie": "tiketa_guest=abc.123.sig"})
SHOWTIME = {
    "id": 7,
    "movie_id": 9,
    "movie_title": "Dune: Part Two",
    "studio_number": 9,
    "starts_at": "2026-11-08T11:00:00Z",
    "starts_at_local": "Sunday 08 November 2026, 18:00 WIB",
    "price_idr": 60000,
    "seats_left": 216,
}
BOOKING = {
    "code": "TK12345678",
    "channel": "chat",
    "showtime": SHOWTIME,
    "seats": ["D9"],
    "customer_name": "Rafi",
    "total_price_idr": 60000,
    "created_at": "2026-11-08T03:00:00Z",
}


def problem(status: int, detail: str, **headers: str) -> httpx.Response:
    body = {"title": "refused", "status": status, "detail": detail}
    return httpx.Response(status, json=body, headers={"Content-Type": "application/problem+json", **headers})


def api_answering(answer: httpx.Response, sent: list[httpx.Request] | None = None) -> BookingApi:
    def handle(request: httpx.Request) -> httpx.Response:
        if sent is not None:
            sent.append(request)
        return answer

    return BookingApi(httpx.AsyncClient(transport=httpx.MockTransport(handle), base_url="http://booking"))


async def test_a_booking_is_sent_as_the_user_with_the_key_that_books_once() -> None:
    sent: list[httpx.Request] = []
    api = api_answering(httpx.Response(201, json=BOOKING), sent)
    order = BookingOrder(showtime_id=7, seats=["D9"], customer_name="Rafi", session_id="s1")
    booking = await api.book(order, idempotency_key_of("s1", "call_00_abc"), GUEST)

    assert booking.code == "TK12345678"
    request = sent[0]
    assert request.method == "POST" and request.url.path == "/v1/bookings"
    assert request.headers["Cookie"] == "tiketa_guest=abc.123.sig"  # the user's own session, not a key of the agent
    assert request.headers["Idempotency-Key"] == idempotency_key_of("s1", "call_00_abc")
    assert json.loads(request.content) == {
        "showtime_id": 7,
        "seats": ["D9"],
        "customer_name": "Rafi",
        "channel": "chat",
        "session_id": "s1",
    }


def test_the_key_is_one_per_tool_call_of_one_conversation_and_fits_the_header() -> None:
    key = idempotency_key_of("s1", "call_00_abc")
    assert key == idempotency_key_of("s1", "call_00_abc") and len(key) == 64
    assert key != idempotency_key_of("s2", "call_00_abc") and key != idempotency_key_of("s1", "call_00_abd")


async def test_showtimes_are_asked_for_one_day_and_film() -> None:
    sent: list[httpx.Request] = []
    api = api_answering(httpx.Response(200, json=[SHOWTIME]), sent)
    showtimes = await api.showtimes_on(date(2026, 11, 8), 9, GUEST)
    assert showtimes[0].starts_at_local.endswith("18:00 WIB")
    assert dict(sent[0].url.params) == {"day": "2026-11-08", "movie_id": "9"}


@pytest.mark.parametrize(
    ("answer", "error"),
    [
        (problem(404, "There is no showtime with id 7"), NotFound),
        (problem(409, "Already taken by someone else: D9"), Conflict),
        (problem(422, "seats.0: 'Z1' is not a seat in this studio"), Conflict),
        (problem(401, "Missing or invalid API key"), Unauthorized),
    ],
)
async def test_a_refusal_keeps_the_booking_services_own_words(answer: httpx.Response, error: type[Exception]) -> None:
    with pytest.raises(error) as refusal:
        await api_answering(answer).get_showtime(7, GUEST)
    assert str(refusal.value) == answer.json()["detail"]


async def test_too_many_requests_say_when_to_try_again() -> None:
    with pytest.raises(RateLimited) as limited:
        await api_answering(problem(429, "Over 60 requests a minute.", **{"Retry-After": "40"})).get_showtime(7, GUEST)
    assert limited.value.retry_after_seconds == 40


async def test_a_booking_service_that_is_down_or_broken_is_never_papered_over() -> None:
    def refuse_connection(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    down = BookingApi(httpx.AsyncClient(transport=httpx.MockTransport(refuse_connection), base_url="http://booking"))
    with pytest.raises(BookingApiUnavailable, match="did not answer"):
        await down.seat_map(7, GUEST)
    with pytest.raises(BookingApiUnavailable, match="answered 500"):
        await api_answering(httpx.Response(500, text="boom")).seat_map(7, GUEST)


def request_with(headers: dict[str, str]) -> Request:
    raw_headers = [(name.lower().encode(), value.encode()) for name, value in headers.items()]
    scope: dict[str, Any] = {"type": "http", "method": "GET", "path": "/", "headers": raw_headers}
    return Request(scope)


def test_only_the_callers_credentials_are_passed_on() -> None:
    browser = request_with({"Cookie": "theme=dark; tiketa_guest=abc.123.sig", "User-Agent": "Firefox"})
    assert credentials_of(browser) == {"Cookie": "tiketa_guest=abc.123.sig"}
    server = request_with({"X-API-Key": "live-key", "Authorization": "Bearer something-else"})
    assert credentials_of(server) == {"X-API-Key": "live-key"}
    assert credentials_of(request_with({})) == {}
    assert "abc.123.sig" not in repr(GUEST)  # credentials stay out of logs and traces


def test_production_needs_a_key_for_the_booking_service() -> None:
    with pytest.raises(ValueError, match="BOOKING_API_KEY"):
        Settings(_env_file=None, environment="production", database_url="sqlite+aiosqlite://")  # type: ignore[call-arg]

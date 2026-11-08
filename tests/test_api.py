from typing import Any

import httpx
import pytest
from langchain_core.messages import ToolMessage

from app.cinema.schemas import Showtime
from app.cinema.seat_layout import ROWS_FRONT_TO_BACK
from app.cinema.store import CinemaStore
from app.features.chat.service import ChatService

from conftest import FakeReader, parse_events
from fakes import ScriptedChatModel, calls, says


def booking_replies(showtime: Showtime) -> list[Any]:
    choose = ("update_booking", {"showtime_id": showtime.id, "seats": ["D9", "D10"], "customer_name": "Rafi"})
    return [calls(choose), calls(("book_tickets", {}))]


async def start(client: httpx.AsyncClient) -> str:
    response = await client.post("/v1/sessions")
    assert response.status_code == 201
    session_id: str = response.json()["session_id"]
    return session_id


async def send(client: httpx.AsyncClient, session_id: str, text: str) -> list[dict[str, Any]]:
    response = await client.post(f"/v1/sessions/{session_id}/messages", json={"message": text})
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/event-stream")
    return parse_events(response.text)


async def test_a_conversation_books_only_after_confirm(
    client: httpx.AsyncClient, model: ScriptedChatModel, dune_today: list[Showtime]
) -> None:
    model.replies += [*booking_replies(dune_today[2]), says("Sudah dipesan, kodenya ada di atas.")]
    session_id = await start(client)

    events = await send(client, session_id, "dune jam 6 sore, 2 kursi tengah, atas nama Rafi")
    assert [event["type"] for event in events] == ["tool", "tool", "confirmation", "end"]
    assert events[2]["data"]["seats"] == ["D9", "D10"]
    assert events[-1]["data"]["model_calls"] == 2
    view = (await client.get(f"/v1/sessions/{session_id}")).json()
    assert view["pending_confirmation"]["total_price_idr"] == 2 * dune_today[2].price_idr
    assert view["bookings"] == []

    response = await client.post(f"/v1/sessions/{session_id}/confirmation", json={"approved": True})
    events = parse_events(response.text)
    assert [event["type"] for event in events] == ["booking", "message", "end"]
    view = (await client.get(f"/v1/sessions/{session_id}")).json()
    assert view["pending_confirmation"] is None
    assert view["bookings"][0]["code"] == events[0]["data"]["code"]
    assert [turn["role"] for turn in view["turns"]] == ["user", "assistant"]


async def test_a_typed_yes_while_a_booking_waits_is_read_by_the_model(
    client: httpx.AsyncClient, model: ScriptedChatModel, reader: FakeReader, dune_today: list[Showtime]
) -> None:
    model.replies += [*booking_replies(dune_today[2]), says("Siap, sudah dipesan.")]
    session_id = await start(client)
    await send(client, session_id, "dune jam 6 sore, 2 kursi tengah, atas nama Rafi")
    reader.approve = True
    events = await send(client, session_id, "iya gas")
    assert reader.replies_read == ["iya gas"]
    assert "booking" in [event["type"] for event in events]
    view = (await client.get(f"/v1/sessions/{session_id}")).json()
    assert [turn["text"] for turn in view["turns"]] == [
        "dune jam 6 sore, 2 kursi tengah, atas nama Rafi",
        "iya gas",
        "Siap, sudah dipesan.",
    ]


async def test_confirming_with_nothing_waiting_is_a_conflict(client: httpx.AsyncClient) -> None:
    session_id = await start(client)
    response = await client.post(f"/v1/sessions/{session_id}/confirmation", json={"approved": True})
    assert response.status_code == 409
    assert response.headers["content-type"] == "application/problem+json"


async def test_another_caller_cannot_see_or_use_a_conversation(client: httpx.AsyncClient) -> None:
    session_id = await start(client)
    other = {"X-API-Key": "other-key-0002"}
    assert (await client.get(f"/v1/sessions/{session_id}", headers=other)).status_code == 404
    sent = await client.post(f"/v1/sessions/{session_id}/messages", json={"message": "halo"}, headers=other)
    assert sent.status_code == 404


async def test_a_second_message_while_a_turn_runs_is_a_conflict(client: httpx.AsyncClient, chat: ChatService) -> None:
    session_id = await start(client)
    await chat.begin_turn(session_id)  # as if a reply were still streaming
    response = await client.post(f"/v1/sessions/{session_id}/messages", json={"message": "halo"})
    assert response.status_code == 409


async def test_a_failed_turn_says_so_and_the_conversation_carries_on(
    client: httpx.AsyncClient, model: ScriptedChatModel, store: CinemaStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def database_down(*args: Any) -> None:
        raise ConnectionError("database unreachable")

    model.replies += [calls(("get_seat_map", {"showtime_id": 1})), says("Halo, ada yang bisa dibantu?")]
    session_id = await start(client)
    with monkeypatch.context() as patch:
        patch.setattr(store, "get_showtime", database_down)
        events = await send(client, session_id, "kursi yang kosong apa aja?")
    assert events[-2]["type"] == "error" and events[-1]["type"] == "end"

    events = await send(client, session_id, "halo")
    assert [event["type"] for event in events] == ["message", "end"]
    unfinished_call_answer = model.received[-1][-3]  # before the new message and the turn context
    assert isinstance(unfinished_call_answer, ToolMessage) and "previous turn failed" in unfinished_call_answer.text


async def test_the_catalog_lists_films_showtimes_and_seats(client: httpx.AsyncClient) -> None:
    movies = (await client.get("/v1/movies")).json()
    assert len(movies) == 21
    showtimes = (await client.get("/v1/showtimes", params={"day": "2026-11-08", "movie_id": 9})).json()
    assert [showtime["starts_at"] for showtime in showtimes][0] == "2026-11-08T05:30:00Z"
    seats = (await client.get(f"/v1/showtimes/{showtimes[0]['id']}/seats")).json()
    assert [row["row"] for row in seats["rows"]] == list(ROWS_FRONT_TO_BACK)


async def test_requests_without_the_api_key_are_refused(client: httpx.AsyncClient) -> None:
    assert (await client.get("/v1/movies", headers={"X-API-Key": "wrong"})).status_code == 401
    assert (await client.get("/health", headers={"X-API-Key": "wrong"})).status_code == 200


async def test_a_failure_before_the_agent_runs_is_an_error_event_and_frees_the_turn(
    client: httpx.AsyncClient, model: ScriptedChatModel, reader: FakeReader, dune_today: list[Showtime]
) -> None:
    async def reader_down(*args: Any) -> bool:
        raise ConnectionError("model unreachable")

    model.replies += [*booking_replies(dune_today[2])]
    session_id = await start(client)
    await send(client, session_id, "dune jam 6 sore, 2 kursi tengah, atas nama Rafi")
    reader.approves = reader_down  # type: ignore[method-assign]
    events = await send(client, session_id, "iya gas")
    assert [event["type"] for event in events] == ["error", "end"]
    again = await client.post(f"/v1/sessions/{session_id}/confirmation", json={"approved": False})
    assert again.status_code == 200  # the lock was released and the booking still waits

from typing import Any

import httpx

from app.core.token_budget import InMemoryTokenBudget
from app.schemas.cinema import Showtime

from conftest import OWNER, parse_events
from fakes import ScriptedChatModel, calls, says


def form_booking(showtime: Showtime, seats: list[str], name: str = "Sari") -> dict[str, Any]:
    return {"showtime_id": showtime.id, "seats": seats, "customer_name": name}


async def book_on_form(
    client: httpx.AsyncClient, body: dict[str, Any], key: str = "form-key-0001", **headers: str
) -> httpx.Response:
    return await client.post("/v1/bookings", json=body, headers={"Idempotency-Key": key, **headers})


async def test_the_form_books_seats_without_a_conversation(
    client: httpx.AsyncClient, dune_today: list[Showtime]
) -> None:
    evening = dune_today[2]
    response = await book_on_form(client, form_booking(evening, ["F7", "F8"]))
    assert response.status_code == 201
    booking = response.json()
    assert booking["channel"] == "web" and booking["seats"] == ["F7", "F8"]
    assert booking["total_price_idr"] == 2 * evening.price_idr
    seats = (await client.get(f"/v1/showtimes/{evening.id}/seats")).json()
    taken = {seat["id"] for row in seats["rows"] for seat in row["seats"] if seat["is_taken"]}
    assert taken == {"F7", "F8"}


async def test_a_retried_form_request_gets_the_same_booking(
    client: httpx.AsyncClient, dune_today: list[Showtime]
) -> None:
    first = await book_on_form(client, form_booking(dune_today[2], ["F7"]))
    again = await book_on_form(client, form_booking(dune_today[2], ["F7"]))
    assert first.json()["code"] == again.json()["code"]
    assert len((await client.get("/v1/bookings")).json()) == 1


async def test_a_seat_the_chat_booked_is_refused_on_the_form(
    client: httpx.AsyncClient, model: ScriptedChatModel, dune_today: list[Showtime]
) -> None:
    evening = dune_today[2]
    choice = {"showtime_id": evening.id, "seats": ["D9"], "customer_name": "Rafi"}
    model.replies += [calls(("update_booking", choice)), calls(("book_tickets", {})), says("Sudah dipesan.")]
    session_id = (await client.post("/v1/sessions")).json()["session_id"]
    await client.post(f"/v1/sessions/{session_id}/messages", json={"message": "dune jam 6, D9, Rafi"})
    await client.post(f"/v1/sessions/{session_id}/confirmation", json={"approved": True})

    response = await book_on_form(client, form_booking(evening, ["D9", "D10"]))
    assert response.status_code == 409 and "D9" in response.json()["detail"]
    bookings = (await client.get("/v1/bookings")).json()
    assert [booking["channel"] for booking in bookings] == ["chat"]  # D10 was not taken on its own either


async def test_the_list_holds_both_channels_and_only_the_callers_own(
    client: httpx.AsyncClient, dune_today: list[Showtime]
) -> None:
    await book_on_form(client, form_booking(dune_today[2], ["A1"]), key="form-key-0001")
    await book_on_form(client, form_booking(dune_today[2], ["A2"]), key="form-key-0002")
    other = await book_on_form(
        client, form_booking(dune_today[2], ["A3"]), key="form-key-0001", **{"X-API-Key": "other-key-0002"}
    )
    assert other.status_code == 201  # the same key from another caller is another booking
    mine = (await client.get("/v1/bookings")).json()
    assert [booking["seats"] for booking in mine] == [["A2"], ["A1"]]  # newest first


async def test_the_form_keeps_the_seat_limit_and_needs_a_key(
    client: httpx.AsyncClient, dune_today: list[Showtime]
) -> None:
    nine = [f"G{number}" for number in range(1, 10)]
    assert (await book_on_form(client, form_booking(dune_today[2], nine))).status_code == 409
    missing_key = await client.post("/v1/bookings", json=form_booking(dune_today[2], ["G1"]))
    assert missing_key.status_code == 422


async def test_chat_turns_stop_when_the_days_tokens_are_used_up(
    client: httpx.AsyncClient, model: ScriptedChatModel, budget: InMemoryTokenBudget
) -> None:
    model.replies += [says("Halo, ada yang bisa dibantu?")]
    session_id = (await client.post("/v1/sessions")).json()["session_id"]
    events = parse_events((await client.post(f"/v1/sessions/{session_id}/messages", json={"message": "halo"})).text)
    usage = (await client.get("/v1/usage")).json()
    assert usage["used_tokens"] == events[-1]["data"]["input_tokens"] + events[-1]["data"]["output_tokens"] > 0

    await budget.add(OWNER, usage["daily_tokens"])
    refused = await client.post(f"/v1/sessions/{session_id}/messages", json={"message": "halo lagi"})
    assert refused.status_code == 429 and int(refused.headers["Retry-After"]) > 0
    assert "used up" in refused.json()["detail"]


async def test_the_chat_closes_for_everyone_at_the_days_total_and_the_form_still_books(
    client: httpx.AsyncClient, budget: InMemoryTokenBudget, dune_today: list[Showtime]
) -> None:
    session_id = (await client.post("/v1/sessions")).json()["session_id"]
    await budget.add("guest:many-other-callers", 50_000)
    refused = await client.post(f"/v1/sessions/{session_id}/messages", json={"message": "halo"})
    assert refused.status_code == 429 and "closed for today" in refused.json()["detail"]
    assert (await book_on_form(client, form_booking(dune_today[2], ["J1"]))).status_code == 201

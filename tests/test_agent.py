from typing import Any

import pytest
from langchain.agents.middleware.model_call_limit import ModelCallLimitExceededError
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command
from litellm.exceptions import MidStreamFallbackError

from app.schemas.agent import ChatContext
from app.schemas.cinema import Showtime
from app.services.booking_agent import build_agent
from app.settings import Settings

from conftest import CALLER, NOW
from fakes import FakeBookingApi, ScriptedChatModel, calls, says

Agent = CompiledStateGraph[Any, Any, Any, Any]
CONFIG: Any = {"configurable": {"thread_id": "s1"}}
CONTEXT = ChatContext(session_id="s1", caller=CALLER, now=NOW)


def choose(showtime: Showtime, seats: list[str], name: str | None = "Rafi") -> tuple[str, dict[str, Any]]:
    args: dict[str, Any] = {"showtime_id": showtime.id, "seats": seats}
    if name is not None:
        args["customer_name"] = name
    return ("update_booking", args)


async def ask(agent: Agent, text: str) -> dict[str, Any]:
    return await agent.ainvoke({"messages": [HumanMessage(text)]}, CONFIG, context=CONTEXT)  # type: ignore[no-any-return]


async def tool_messages(agent: Agent) -> list[ToolMessage]:
    state = await agent.aget_state(CONFIG)
    return [message for message in state.values["messages"] if isinstance(message, ToolMessage)]


async def test_a_booking_waits_for_the_user_then_books_what_was_shown(
    agent: Agent, model: ScriptedChatModel, api: FakeBookingApi, dune_today: list[Showtime]
) -> None:
    evening = dune_today[2]
    model.replies += [calls(choose(evening, ["D9", "D10"])), calls(("book_tickets", {})), says("Sudah dipesan.")]
    await ask(agent, "dune jam 6 sore, 2 kursi tengah, atas nama Rafi")

    waiting = (await agent.aget_state(CONFIG)).interrupts
    summary = waiting[0].value["summary"]
    assert summary["seats"] == ["D9", "D10"]
    assert summary["total_price_idr"] == 2 * evening.price_idr  # priced by the booking service, not by the model
    assert await api.bookings_of_session("s1", CALLER) == []

    await agent.ainvoke(Command(resume={"approved": True}), CONFIG, context=CONTEXT)
    bookings = await api.bookings_of_session("s1", CALLER)
    assert [booking.seats for booking in bookings] == [["D9", "D10"]]
    state = await agent.aget_state(CONFIG)
    assert state.values["draft"]["seats"] == [] and state.values["draft"]["customer_name"] == "Rafi"
    assert bookings[0].code in (await tool_messages(agent))[-1].text


async def test_every_call_to_the_booking_service_is_made_as_the_person_in_the_conversation(
    agent: Agent, model: ScriptedChatModel, api: FakeBookingApi, dune_today: list[Showtime]
) -> None:
    today = NOW.date().isoformat()
    model.replies += [
        calls(("find_showtimes", {"day": today})),
        calls(choose(dune_today[2], ["A1"])),
        calls(("book_tickets", {})),
        says("Sudah dipesan."),
    ]
    await ask(agent, "dune jam 6, A1, Rafi")
    await agent.ainvoke(Command(resume={"approved": True}), CONFIG, context=CONTEXT)
    assert api.seen_callers and all(caller == CALLER for caller in api.seen_callers)
    assert [owner for owner, _, _, _ in api.bookings] == [CALLER.name]


async def test_cancel_books_nothing(
    agent: Agent, model: ScriptedChatModel, api: FakeBookingApi, dune_today: list[Showtime]
) -> None:
    model.replies += [calls(choose(dune_today[2], ["A1"])), calls(("book_tickets", {})), says("Oke, dibatalkan.")]
    await ask(agent, "dune jam 6, A1, Rafi")
    await agent.ainvoke(Command(resume={"approved": False}), CONFIG, context=CONTEXT)
    assert await api.bookings_of_session("s1", CALLER) == []
    assert "pressed Cancel" in (await tool_messages(agent))[-1].text


async def test_a_typed_reply_to_the_confirmation_joins_the_conversation(
    agent: Agent, model: ScriptedChatModel, dune_today: list[Showtime]
) -> None:
    model.replies += [calls(choose(dune_today[2], ["A1"])), calls(("book_tickets", {})), says("Mau ganti ke mana?")]
    await ask(agent, "dune jam 6, A1, Rafi")
    await agent.ainvoke(Command(resume={"approved": False, "user_message": "ganti D5 aja"}), CONFIG, context=CONTEXT)
    tool_result, typed_reply = model.received[-1][-3:-1]  # the turn context comes last
    assert isinstance(tool_result, ToolMessage) and "instead of confirming" in tool_result.text
    assert isinstance(typed_reply, HumanMessage) and typed_reply.text == "ganti D5 aja"


async def test_a_taken_seat_goes_back_to_the_model_and_changes_nothing(
    agent: Agent, model: ScriptedChatModel, api: FakeBookingApi, dune_today: list[Showtime]
) -> None:
    evening = dune_today[2]
    await api.someone_else_books(evening, ["D9"])
    model.replies += [calls(choose(evening, ["D9", "D10"])), says("D9 sudah terisi.")]
    await ask(agent, "dune jam 6, D9 dan D10")
    refusal = (await tool_messages(agent))[-1]
    assert refusal.status == "error" and "Already taken: D9" in refusal.text
    assert (await agent.aget_state(CONFIG)).values.get("draft", {}) == {}


async def test_a_seat_the_booking_service_does_not_know_is_refused(
    agent: Agent, model: ScriptedChatModel, dune_today: list[Showtime]
) -> None:
    model.replies += [calls(choose(dune_today[2], ["d5", "K3"])), says("Kursinya D5 ya?")]
    await ask(agent, "dune jam 6 kursi d5")
    refusal = (await tool_messages(agent))[-1]
    assert refusal.status == "error" and "d5, K3 is not a seat" in refusal.text
    assert (await agent.aget_state(CONFIG)).values.get("draft", {}) == {}


async def test_book_tickets_refuses_a_booking_with_something_missing(
    agent: Agent, model: ScriptedChatModel, dune_today: list[Showtime]
) -> None:
    model.replies += [calls(choose(dune_today[2], ["A1"], name=None)), calls(("book_tickets", {})), says("Atas nama?")]
    await ask(agent, "dune jam 6 kursi A1")
    assert not (await agent.aget_state(CONFIG)).interrupts
    assert "Still needed: name on the booking" in (await tool_messages(agent))[-1].text


async def test_book_tickets_must_be_called_on_its_own(
    agent: Agent, model: ScriptedChatModel, dune_today: list[Showtime]
) -> None:
    model.replies += [calls(choose(dune_today[2], ["A1"]), ("book_tickets", {})), says("Sebentar.")]
    await ask(agent, "dune jam 6 kursi A1 atas nama Rafi, langsung pesan")
    assert not (await agent.aget_state(CONFIG)).interrupts
    assert any("on its own" in message.text for message in await tool_messages(agent))


async def test_a_seat_sold_while_the_user_decides_is_not_booked_twice(
    agent: Agent, model: ScriptedChatModel, api: FakeBookingApi, dune_today: list[Showtime]
) -> None:
    evening = dune_today[2]
    model.replies += [calls(choose(evening, ["D9"])), calls(("book_tickets", {})), says("Maaf, D9 baru saja terisi.")]
    await ask(agent, "dune jam 6, D9, Rafi")
    await api.someone_else_books(evening, ["D9"])
    await agent.ainvoke(Command(resume={"approved": True}), CONFIG, context=CONTEXT)
    assert await api.bookings_of_session("s1", CALLER) == []
    assert "Already taken: D9" in (await tool_messages(agent))[-1].text


async def test_the_seat_map_reads_as_the_room_with_taken_seats_the_aisle_and_the_walkway(
    agent: Agent, model: ScriptedChatModel, api: FakeBookingApi, dune_today: list[Showtime]
) -> None:
    await api.someone_else_books(dune_today[2], ["A9", "M18"])
    model.replies += [calls(("get_seat_map", {"showtime_id": dune_today[2].id})), says("Ini kursinya.")]
    await ask(agent, "kursi yang kosong apa aja?")
    lines = (await tool_messages(agent))[-1].text.splitlines()
    assert lines[0].startswith("Dune: Part Two, Sunday 08 November 2026, 18:00 WIB, studio 9")
    assert "rows E to H, seats 6 to 13" in lines[1]
    assert lines[2] == "SCREEN (front)" and "A8 -- | A10" in lines[3]
    assert lines[13] == "(walkway)" and lines[-2].endswith("M17 --")


async def test_the_last_message_holds_the_local_time_and_the_booking_so_far(
    agent: Agent, model: ScriptedChatModel, dune_today: list[Showtime]
) -> None:
    model.replies += [calls(choose(dune_today[2], ["D9"], name=None)), says("Atas nama siapa?")]
    await ask(agent, "dune jam 6, D9")
    first_context, second_context = (calls_seen[-1] for calls_seen in model.received)
    assert isinstance(first_context, SystemMessage) and isinstance(second_context, SystemMessage)
    assert "Now: Sunday 08 November 2026, 10:00 WIB" in first_context.text
    assert "Still needed: showtime, seats, name on the booking" in first_context.text
    assert "- Seats: D9" in second_context.text and "Still needed: name on the booking" in second_context.text


async def test_every_call_starts_with_the_same_text_so_the_provider_can_cache_it(
    agent: Agent, model: ScriptedChatModel, dune_today: list[Showtime]
) -> None:
    model.replies += [calls(choose(dune_today[2], ["D9"], name=None)), says("Atas nama siapa?")]
    await ask(agent, "dune jam 6, D9")
    first_call, second_call = model.received
    assert second_call[: len(first_call) - 1] == first_call[:-1]  # only the context at the end differs
    assert all(not isinstance(message, SystemMessage) or "Now:" not in message.text for message in second_call[:-1])
    state = await agent.aget_state(CONFIG)
    assert not any(isinstance(message, SystemMessage) for message in state.values["messages"])


async def test_a_turn_that_keeps_calling_tools_is_stopped(
    model: ScriptedChatModel, api: FakeBookingApi, settings: Settings
) -> None:
    limited = settings.model_copy(update={"max_model_calls_per_turn": 2})
    api_any: Any = api
    agent = build_agent(
        model, api_any, await api.list_movies(CALLER), await api.cinema(CALLER), limited, InMemorySaver()
    )
    model.replies += [calls(("find_showtimes", {"day": "2026-11-08"})) for _ in range(3)]
    with pytest.raises(ModelCallLimitExceededError):
        await ask(agent, "jadwal hari ini")


async def test_a_stream_the_provider_drops_is_tried_once_more(agent: Agent, model: ScriptedChatModel) -> None:
    dropped = MidStreamFallbackError("Connection closed", model="deepseek-flash", llm_provider="deepseek")
    model.replies += [dropped, says("Halo! Mau nonton apa?")]
    result = await ask(agent, "halo")
    assert result["messages"][-1].text == "Halo! Mau nonton apa?"

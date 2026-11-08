from typing import Any

import pytest
from langchain.agents.middleware.model_call_limit import ModelCallLimitExceededError
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command
from litellm.exceptions import MidStreamFallbackError

from app.cinema.schemas import BookingRequest, Showtime
from app.cinema.store import CinemaStore
from app.features.chat.agent import build_agent
from app.features.chat.state import ChatContext
from config.settings import Settings

from conftest import CINEMA_TIMEZONE, NOW
from fakes import ScriptedChatModel, calls, says

Agent = CompiledStateGraph[Any, Any, Any, Any]
CONFIG: Any = {"configurable": {"thread_id": "s1"}}
CONTEXT = ChatContext(session_id="s1", now=NOW)


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


async def someone_else_books(store: CinemaStore, showtime: Showtime, seats: list[str]) -> None:
    other = BookingRequest(
        idempotency_key="other", session_id="s2", showtime_id=showtime.id, seats=seats, customer_name="X"
    )
    await store.book(other, NOW)


async def test_a_booking_waits_for_the_user_then_books_what_was_shown(
    agent: Agent, model: ScriptedChatModel, store: CinemaStore, dune_today: list[Showtime]
) -> None:
    evening = dune_today[2]
    model.replies += [calls(choose(evening, ["D9", "D10"])), calls(("book_tickets", {})), says("Sudah dipesan.")]
    await ask(agent, "dune jam 6 sore, 2 kursi tengah, atas nama Rafi")

    waiting = (await agent.aget_state(CONFIG)).interrupts
    summary = waiting[0].value["summary"]
    assert summary["seats"] == ["D9", "D10"]
    assert summary["total_price_idr"] == 2 * evening.price_idr  # priced from the database, not by the model
    assert await store.bookings_for_session("s1") == []

    await agent.ainvoke(Command(resume={"approved": True}), CONFIG, context=CONTEXT)
    bookings = await store.bookings_for_session("s1")
    assert [booking.seats for booking in bookings] == [["D9", "D10"]]
    state = await agent.aget_state(CONFIG)
    assert state.values["draft"]["seats"] == [] and state.values["draft"]["customer_name"] == "Rafi"
    assert bookings[0].code in (await tool_messages(agent))[-1].text


async def test_cancel_books_nothing(
    agent: Agent, model: ScriptedChatModel, store: CinemaStore, dune_today: list[Showtime]
) -> None:
    model.replies += [calls(choose(dune_today[2], ["A1"])), calls(("book_tickets", {})), says("Oke, dibatalkan.")]
    await ask(agent, "dune jam 6, A1, Rafi")
    await agent.ainvoke(Command(resume={"approved": False}), CONFIG, context=CONTEXT)
    assert await store.bookings_for_session("s1") == []
    assert "pressed Cancel" in (await tool_messages(agent))[-1].text


async def test_a_typed_reply_to_the_confirmation_joins_the_conversation(
    agent: Agent, model: ScriptedChatModel, dune_today: list[Showtime]
) -> None:
    model.replies += [calls(choose(dune_today[2], ["A1"])), calls(("book_tickets", {})), says("Mau ganti ke mana?")]
    await ask(agent, "dune jam 6, A1, Rafi")
    await agent.ainvoke(Command(resume={"approved": False, "user_message": "ganti D5 aja"}), CONFIG, context=CONTEXT)
    tool_result, typed_reply = model.received[-1][-2:]
    assert isinstance(tool_result, ToolMessage) and "instead of confirming" in tool_result.text
    assert isinstance(typed_reply, HumanMessage) and typed_reply.text == "ganti D5 aja"


async def test_a_taken_seat_goes_back_to_the_model_and_changes_nothing(
    agent: Agent, model: ScriptedChatModel, store: CinemaStore, dune_today: list[Showtime]
) -> None:
    evening = dune_today[2]
    await someone_else_books(store, evening, ["D9"])
    model.replies += [calls(choose(evening, ["D9", "D10"])), says("D9 sudah terisi.")]
    await ask(agent, "dune jam 6, D9 dan D10")
    refusal = (await tool_messages(agent))[-1]
    assert refusal.status == "error" and "Already taken: D9" in refusal.text
    assert (await agent.aget_state(CONFIG)).values.get("draft", {}) == {}


async def test_an_unknown_seat_id_is_refused_before_the_tool_runs(
    agent: Agent, model: ScriptedChatModel, dune_today: list[Showtime]
) -> None:
    model.replies += [calls(choose(dune_today[2], ["d5"])), says("Kursinya D5 ya?")]
    await ask(agent, "dune jam 6 kursi d5")
    refusal = (await tool_messages(agent))[-1]
    assert refusal.status == "error" and "not a seat" in refusal.text


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
    agent: Agent, model: ScriptedChatModel, store: CinemaStore, dune_today: list[Showtime]
) -> None:
    evening = dune_today[2]
    model.replies += [calls(choose(evening, ["D9"])), calls(("book_tickets", {})), says("Maaf, D9 baru saja terisi.")]
    await ask(agent, "dune jam 6, D9, Rafi")
    await someone_else_books(store, evening, ["D9"])
    await agent.ainvoke(Command(resume={"approved": True}), CONFIG, context=CONTEXT)
    assert await store.bookings_for_session("s1") == []
    assert "Already taken: D9" in (await tool_messages(agent))[-1].text


async def test_the_prompt_holds_the_local_time_and_the_booking_so_far(
    agent: Agent, model: ScriptedChatModel, dune_today: list[Showtime]
) -> None:
    model.replies += [calls(choose(dune_today[2], ["D9"], name=None)), says("Atas nama siapa?")]
    await ask(agent, "dune jam 6, D9")
    first_prompt, second_prompt = (calls_seen[0] for calls_seen in model.received)
    assert isinstance(first_prompt, SystemMessage) and isinstance(second_prompt, SystemMessage)
    assert "Now: Sunday 08 November 2026, 10:00 WIB" in first_prompt.text
    assert "Still needed: showtime, seats, name on the booking" in first_prompt.text
    assert "- Seats: D9" in second_prompt.text and "Still needed: name on the booking" in second_prompt.text


async def test_a_turn_that_keeps_calling_tools_is_stopped(
    model: ScriptedChatModel, store: CinemaStore, settings: Settings
) -> None:
    limited = settings.model_copy(update={"max_model_calls_per_turn": 2})
    agent = build_agent(model, store, await store.list_movies(), limited, CINEMA_TIMEZONE, InMemorySaver())
    model.replies += [calls(("find_showtimes", {"day": "2026-11-08"})) for _ in range(3)]
    with pytest.raises(ModelCallLimitExceededError):
        await ask(agent, "jadwal hari ini")


async def test_a_stream_the_provider_drops_is_tried_once_more(agent: Agent, model: ScriptedChatModel) -> None:
    dropped = MidStreamFallbackError("Connection closed", model="deepseek-flash", llm_provider="deepseek")
    model.replies += [dropped, says("Halo! Mau nonton apa?")]
    result = await ask(agent, "halo")
    assert result["messages"][-1].text == "Halo! Mau nonton apa?"

import json
from typing import Any

import httpx

from app.repositories.gatekeeper import Gatekeeper
from app.services.chat import GATE_DOWN_TEXT, REFUSALS, ChatService

from conftest import parse_events
from fakes import ScriptedChatModel, says


def gate_answering(blocked_by: str | None, seen: list[dict[str, Any]]) -> Gatekeeper:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(
            200, json={"blocked": blocked_by is not None, "blocked_by": blocked_by, "decision_ms": 210}
        )

    return Gatekeeper(httpx.AsyncClient(base_url="http://gate", transport=httpx.MockTransport(handler)), "tiketa")


async def send(client: httpx.AsyncClient, text: str) -> list[dict[str, Any]]:
    session_id = (await client.post("/v1/sessions")).json()["session_id"]
    response = await client.post(f"/v1/sessions/{session_id}/messages", json={"message": text})
    return parse_events(response.text)


async def test_an_off_topic_message_is_refused_without_calling_the_model(
    client: httpx.AsyncClient, chat: ChatService, model: ScriptedChatModel
) -> None:
    seen: list[dict[str, Any]] = []
    chat._gate = gate_answering("off_topic", seen)
    events = await send(client, "buatkan script python kalkulator")
    assert [event["type"] for event in events] == ["message", "end"]
    assert events[0]["text"] == REFUSALS["off_topic"] and events[0]["data"]["blocked_by"] == "off_topic"
    assert model.received == []
    assert seen == [
        {"messages": [{"role": "user", "content": "buatkan script python kalkulator"}], "scope_name": "tiketa"}
    ]


async def test_an_allowed_message_reaches_the_agent(
    client: httpx.AsyncClient, chat: ChatService, model: ScriptedChatModel
) -> None:
    chat._gate = gate_answering(None, [])
    model.replies += [says("Halo! Mau nonton apa?")]
    events = await send(client, "Hai")
    assert "Halo! Mau nonton apa?" in "".join(event.get("text", "") for event in events)
    assert len(model.received) == 1


async def test_the_agent_reads_nothing_unchecked_when_the_gate_is_down(
    client: httpx.AsyncClient, chat: ChatService, model: ScriptedChatModel
) -> None:
    down = httpx.AsyncClient(base_url="http://gate", transport=httpx.MockTransport(lambda request: httpx.Response(503)))
    chat._gate = Gatekeeper(down, "tiketa")
    events = await send(client, "Hai")
    assert [(event["type"], event.get("text")) for event in events][0] == ("error", GATE_DOWN_TEXT)
    assert model.received == []

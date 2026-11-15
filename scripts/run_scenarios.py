"""Play the conversations in evals/scenarios.json against a running service and grade every reply.

Checks in code: the events a turn must or must not produce, and the bookings each conversation ends with.
The judge (JUDGE_MODEL) reads each reply against the expected behaviour. Check it against your own reading first.
Each turn's tool calls (name, arguments, result) are read from the saved conversation and kept in the transcript,
which evals/test_conversations.py grades with DeepEval.

The agent books through the booking API (tiketa-app), which must be running with this week published.

Usage: python scripts/run_scenarios.py [--url http://127.0.0.1:8060] [--key KEY] [--only NAME] [--no-judge]
"""

import argparse
import asyncio
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

import httpx
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.checkpoint.base import BaseCheckpointSaver
from pydantic import BaseModel, Field

from app.core.checkpoints import open_checkpointer
from app.engines.llm import build_chat_model
from app.generative.prompts import JUDGE_PROMPT
from app.repositories.booking_api import BookingApi
from app.services.chat import config_of
from app.settings import get_settings
from app.tools.booking import build_tools
from app.utils.clock import local_text

SCENARIOS = Path("evals/scenarios.json")
RESULTS = Path("evals/results")


class Turn(BaseModel):
    say: str | None = None
    press: Literal["confirm", "cancel"] | None = None
    events: list[str] = Field(default_factory=list, description="Event types this turn must produce")
    forbid: list[str] = Field(default_factory=list, description="Event types this turn must not produce")
    expect: str


class Scenario(BaseModel):
    name: str
    turns: list[Turn]
    bookings: int


class Verdict(BaseModel):
    verdict: Literal["pass", "fail", "unsure"]
    reasoning: str = Field(description="One or two sentences")


def parse_events(body: str) -> list[dict[str, Any]]:
    return [json.loads(line[len("data: ") :]) for line in body.splitlines() if line.startswith("data: ")]


def summary_shown(events: list[dict[str, Any]]) -> str:
    """The summary card a turn put on the user's screen, in words. Empty when the turn showed none."""
    summary = next((event["data"] for event in events if event["type"] == "confirmation"), None)
    if summary is None:
        return ""
    return (
        f"The system shows the user this booking summary with Confirm and Cancel buttons: {summary['movie_title']}, "
        f"{summary['starts_at_local']}, studio {summary['studio_number']}, seats {', '.join(summary['seats'])}, "
        f"name {summary['customer_name']}, total {summary['total_price_idr']} IDR"
    )


def tools_of_turn(messages: list[BaseMessage], seen_ids: set[str | None], shown: str) -> list[dict[str, Any]]:
    """The tool calls answered in this turn, then the one this turn left waiting for the user's answer."""
    calls = {call["id"]: call for message in messages if isinstance(message, AIMessage) for call in message.tool_calls}
    results = [message for message in messages if isinstance(message, ToolMessage)]
    answered_ids = {result.tool_call_id for result in results}
    answered = [
        {**calls[result.tool_call_id], "output": result.text}
        for result in results
        if result.id not in seen_ids and result.tool_call_id in calls
    ]
    waiting = [
        {**call, "output": f"Paused, nothing is booked yet. {shown}"}
        for message in messages
        if isinstance(message, AIMessage) and message.id not in seen_ids
        for call in message.tool_calls
        if call["id"] not in answered_ids
    ]
    return [{"name": call["name"], "arguments": call["args"], "output": call["output"]} for call in answered + waiting]


async def play(
    client: httpx.AsyncClient,
    scenario: Scenario,
    judge: Any,
    cinema_timezone: ZoneInfo,
    checkpointer: BaseCheckpointSaver[Any],
) -> list[dict[str, Any]]:
    session_id = (await client.post("/v1/sessions")).json()["session_id"]
    history: list[str] = []
    seen_ids: set[str | None] = set()
    rows: list[dict[str, Any]] = []
    for number, turn in enumerate(scenario.turns, start=1):  # each turn builds on the previous one
        started = time.perf_counter()
        body: dict[str, Any]
        if turn.press is not None:
            path, body, user = "confirmation", {"approved": turn.press == "confirm"}, f"[pressed {turn.press}]"
        else:
            path, body, user = "messages", {"message": turn.say}, turn.say or ""
        response = await client.post(f"/v1/sessions/{session_id}/{path}", json=body)
        events = parse_events(response.text) if response.status_code == 200 else []
        types = [event["type"] for event in events]
        text = "\n".join(event.get("text", "") for event in events if event["type"] in ("message", "error"))
        shown = summary_shown(events)
        # What the user sees: the agent's words, then the summary card when the turn showed one
        reply = "\n".join(part for part in (text, f"[{shown}]" if shown else "") if part)
        reply = reply or f"(HTTP {response.status_code}: {response.text[:200]})"
        saved = await checkpointer.aget_tuple(config_of(session_id))
        messages: list[BaseMessage] = saved.checkpoint["channel_values"].get("messages", []) if saved else []
        problems = [f"missing {name}" for name in turn.events if name not in types]
        problems += [f"unexpected {name}" for name in turn.forbid if name in types]
        if "error" in types:
            problems.append("error event")
        row: dict[str, Any] = {
            "scenario": scenario.name,
            "turn": number,
            "user": user,
            "text": text,
            "reply": reply,
            "events": [name for name in types if name != "token"],
            "tools": tools_of_turn(messages, seen_ids, shown),
            "token_events": types.count("token"),
            "checks": problems,
            "seconds": round(time.perf_counter() - started, 1),
            "usage": events[-1].get("data") if events else None,
        }
        if judge is not None:
            now_local = local_text(datetime.now(UTC), cinema_timezone)
            prompt = JUDGE_PROMPT.format(now_local=now_local, events=", ".join(types) or "none", expected=turn.expect)
            conversation = "\n".join([*history, f"USER: {user}", f"ASSISTANT: {reply}"])
            verdict = await judge.ainvoke([SystemMessage(prompt), HumanMessage(conversation)])
            row["verdict"], row["reasoning"] = verdict.verdict, verdict.reasoning
        history += [f"USER: {user}", f"ASSISTANT: {reply}"]
        seen_ids |= {message.id for message in messages}
        rows.append(row)
    booked = len((await client.get(f"/v1/sessions/{session_id}")).raise_for_status().json()["bookings"])
    if booked != scenario.bookings:
        rows[-1]["checks"].append(f"{booked} bookings, expected {scenario.bookings}")
    return rows


async def guest_cookies(booking_api_url: str) -> dict[str, str]:
    """A new visitor's guest session from the booking service, as a browser gets it."""
    async with httpx.AsyncClient(base_url=booking_api_url, timeout=10) as visitor:
        return dict((await visitor.post("/auth/guest")).raise_for_status().cookies)


async def play_all(scenarios: list[Scenario], url: str, key: str, judge: Any) -> dict[str, Any]:
    """The transcript: when it was played, the tools the agent had, and one row per turn."""
    settings = get_settings()
    headers = {"X-API-Key": key} if key else {}
    rows: list[dict[str, Any]] = []
    async with httpx.AsyncClient(base_url=settings.booking_api_url, headers=headers, timeout=10) as booking_api:
        cinema = (await booking_api.get("/v1/cinema")).raise_for_status().json()
        tools = build_tools(BookingApi(booking_api), cinema["max_seats_per_booking"])
    cinema_timezone = ZoneInfo(cinema["timezone"])  # the judge reads "besok" from the cinema's clock
    database_url = settings.database_url.get_secret_value()
    async with open_checkpointer(database_url) as checkpointer:
        for scenario in scenarios:  # one at a time keeps provider rate limits simple
            # Without a key each conversation is its own visitor, with its own rate limit at the booking service
            cookies = {} if key else await guest_cookies(settings.booking_api_url)
            async with httpx.AsyncClient(base_url=url, headers=headers, cookies=cookies, timeout=300) as client:
                rows += await play(client, scenario, judge, cinema_timezone, checkpointer)
    return {
        "played_at_local": local_text(datetime.now(UTC), cinema_timezone),
        "agent_model": settings.llm_model,
        "reasoning_effort": settings.llm_reasoning_effort,
        "available_tools": [convert_to_openai_tool(tool)["function"] for tool in tools],  # as the model reads them
        "turns": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8060")
    parser.add_argument("--key", default="")
    parser.add_argument("--only", default="")
    parser.add_argument("--no-judge", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    scenarios = [Scenario.model_validate(item) for item in json.loads(SCENARIOS.read_text(encoding="utf-8"))]
    scenarios = [scenario for scenario in scenarios if args.only in scenario.name]
    judge = None
    if not args.no_judge:
        judge_model = build_chat_model(settings.judge_model, settings, reasoning_effort="none")  # forced tool call
        judge = judge_model.with_structured_output(Verdict, method="function_calling")
    transcript = asyncio.run(play_all(scenarios, args.url, args.key, judge), loop_factory=asyncio.SelectorEventLoop)
    rows = transcript["turns"]

    for row in rows:
        mark = "ok" if not row["checks"] and row.get("verdict", "pass") == "pass" else "CHECK"
        print(f"{mark:5} {row['scenario'][:38]:38} {row['turn']} {row.get('verdict', '-'):6} {row['seconds']:5}s")
        if mark != "ok":
            print(f"      user: {row['user']}")
            print(f"      reply: {row['reply'][:400]}")
            print(f"      checks: {row['checks']}  judge: {row.get('reasoning', '')}")
    passed_checks = sum(not row["checks"] for row in rows)
    print(f"code checks {passed_checks}/{len(rows)} turns")
    if judge is not None:
        print(f"judge pass {sum(row['verdict'] == 'pass' for row in rows)}/{len(rows)} turns")
    input_tokens = sum((row["usage"] or {}).get("input_tokens", 0) for row in rows)
    cached_tokens = sum((row["usage"] or {}).get("cached_input_tokens", 0) for row in rows)
    output_tokens = sum((row["usage"] or {}).get("output_tokens", 0) for row in rows)
    print(f"agent tokens: {input_tokens} in ({cached_tokens} from the prompt cache), {output_tokens} out")
    RESULTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M")
    out = RESULTS / f"{stamp}-{settings.llm_model.replace('/', '_')}.json"
    out.write_text(json.dumps(transcript, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"saved {out}")


if __name__ == "__main__":
    main()

"""Play the conversations in evals/scenarios.json against a running service and grade every reply.

Checks in code: the events a turn must or must not produce, and the bookings each conversation ends with.
The judge (JUDGE_MODEL) reads each reply against the expected behaviour. Check it against your own reading first.

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
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.cinema.clock import local_text
from app.engines.llm import build_chat_model
from config.settings import get_settings

SCENARIOS = Path("evals/scenarios.json")
RESULTS = Path("evals/results")

JUDGE_PROMPT = """You review a cinema ticket assistant. Judge only its latest reply. The history gives context.
Now, in the cinema's timezone: {now_local}. Read dates such as "besok" or "lusa" from this.
First check the language: the reply must be in the language of the user's latest message.
The assistant can find showtimes, read seat maps and prepare a booking. The system then shows the user a summary to
confirm or cancel, and books only after that. Events the system sent in this turn: {events}.
A summary in the reply is what the user sees with Confirm and Cancel buttons: it counts as stating the booking and
asking to confirm it.
Fail when the reply ignores what was asked, contradicts the conversation or the tool results, invents films, times,
prices, seats or bookings, uses another language than the user, claims a booking without a booking code, or does not
match the expected behaviour. Unsure when it depends on data you cannot see. Otherwise pass.
Expected behaviour: {expected}"""


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


def reply_of(events: list[dict[str, Any]]) -> str:
    texts = [event.get("text", "") for event in events if event["type"] in ("message", "error")]
    confirmation = next((event["data"] for event in events if event["type"] == "confirmation"), None)
    shown = f"\n[summary shown to the user: {json.dumps(confirmation, ensure_ascii=False)}]" if confirmation else ""
    return "\n".join(texts) + shown


async def play(client: httpx.AsyncClient, scenario: Scenario, judge: Any) -> list[dict[str, Any]]:
    session_id = (await client.post("/v1/sessions")).json()["session_id"]
    history: list[str] = []
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
        reply = reply_of(events) or f"(HTTP {response.status_code}: {response.text[:200]})"
        problems = [f"missing {name}" for name in turn.events if name not in types]
        problems += [f"unexpected {name}" for name in turn.forbid if name in types]
        if "error" in types:
            problems.append("error event")
        row: dict[str, Any] = {
            "scenario": scenario.name,
            "turn": number,
            "user": user,
            "reply": reply,
            "events": [name for name in types if name != "token"],
            "token_events": types.count("token"),
            "checks": problems,
            "seconds": round(time.perf_counter() - started, 1),
            "usage": events[-1].get("data") if events else None,
        }
        if judge is not None:
            now_local = local_text(datetime.now(UTC), ZoneInfo(get_settings().cinema_timezone))
            prompt = JUDGE_PROMPT.format(now_local=now_local, events=", ".join(types) or "none", expected=turn.expect)
            conversation = "\n".join([*history, f"USER: {user}", f"ASSISTANT: {reply}"])
            verdict = await judge.ainvoke([SystemMessage(prompt), HumanMessage(conversation)])
            row["verdict"], row["reasoning"] = verdict.verdict, verdict.reasoning
        history += [f"USER: {user}", f"ASSISTANT: {reply}"]
        rows.append(row)
    booked = len((await client.get(f"/v1/sessions/{session_id}")).json()["bookings"])
    if booked != scenario.bookings:
        rows[-1]["checks"].append(f"{booked} bookings, expected {scenario.bookings}")
    return rows


async def play_all(scenarios: list[Scenario], url: str, key: str, judge: Any) -> list[dict[str, Any]]:
    headers = {"X-API-Key": key} if key else {}
    rows: list[dict[str, Any]] = []
    async with httpx.AsyncClient(base_url=url, headers=headers, timeout=300) as client:
        for scenario in scenarios:  # one at a time keeps provider rate limits simple
            rows += await play(client, scenario, judge)
    return rows


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
    rows = asyncio.run(play_all(scenarios, args.url, args.key, judge), loop_factory=asyncio.SelectorEventLoop)

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
    output_tokens = sum((row["usage"] or {}).get("output_tokens", 0) for row in rows)
    print(f"agent tokens: {input_tokens} in, {output_tokens} out")
    RESULTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M")
    out = RESULTS / f"{stamp}-{settings.llm_model.replace('/', '_')}.json"
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"saved {out}")


if __name__ == "__main__":
    main()

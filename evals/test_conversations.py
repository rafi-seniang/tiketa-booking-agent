"""Grades a transcript saved by scripts/run_scenarios.py with DeepEval. Nothing here calls the agent.

Per conversation: the scenario's expected behaviour as conditions, tool use (the right tool with the right
arguments), role adherence and the reply language. The judge is JUDGE_MODEL, called on DeepSeek directly.

Usage, from the repository root, in the evaluation environment (make evals-install):
    make evals                                  # the newest transcript in evals/results
    TRANSCRIPT=evals/results/<file>.json make evals
"""

import json
import os
from itertools import groupby
from pathlib import Path
from typing import Any

import pytest
from deepeval import assert_test
from deepeval.dataset import Expectations
from deepeval.metrics import ConversationalGEval, RoleAdherenceMetric, ToolUseMetric
from deepeval.models import DeepSeekModel
from deepeval.test_case import ConversationalTestCase, MultiTurnParams, ToolCall, Turn
from dotenv import dotenv_values
from pydantic import BaseModel

RESULTS = Path("evals/results")
SETTINGS = {**dotenv_values("../../secrets/secrets.env"), **dotenv_values(".env"), **os.environ}
TRANSCRIPT = Path(SETTINGS.get("TRANSCRIPT") or max(RESULTS.glob("*.json"), key=lambda path: path.stat().st_mtime))

CHATBOT_ROLE = (
    "The ticket assistant of a cinema in Jakarta. It answers questions about the films showing (story, year, genre), "
    "helps people find showtimes, choose seats and book tickets, and may offer to do so. It declines anything else "
    "in one sentence. It never books before the user confirms the summary, which the system shows on its behalf."
)
NO_TEXT = "(no text)"
HOW_THE_PRODUCT_WORKS = [
    "The assistant prepares a booking with update_booking and then calls book_tickets. The system, not the "
    "assistant, then shows the user a summary with Confirm and Cancel buttons. The book_tickets result describes it.",
    f"An assistant turn written as {NO_TEXT} means the assistant wrote nothing and the user saw only that summary. "
    "It counts as stating the booking and asking the user to confirm it.",
    "A booking exists only when a book_tickets result gives a booking code.",
    "A user turn written as [pressed confirm] or [pressed cancel] is a button press on that summary.",
    "Seats, showtimes and prices are in the tool results. In a seat map, -- marks a taken seat.",
]
NEVER = ["Say that a booking is made when no book_tickets result in the conversation gives a booking code."]

transcript: dict[str, Any] = json.loads(TRANSCRIPT.read_text(encoding="utf-8"))
scenarios = {scenario["name"]: scenario for scenario in json.loads(Path("evals/scenarios.json").read_text("utf-8"))}


class DeepSeekJudge(DeepSeekModel):
    """DeepSeek's JSON mode is not given the fields DeepEval will validate, so the prompt carries the schema."""

    async def a_generate(self, prompt: str, schema: type[BaseModel] | None = None, audio: Any = None) -> Any:
        return await super().a_generate(with_schema(prompt, schema), schema, audio)

    def generate(self, prompt: str, schema: type[BaseModel] | None = None, audio: Any = None) -> Any:
        return super().generate(with_schema(prompt, schema), schema, audio)


def with_schema(prompt: str, schema: type[BaseModel] | None) -> str:
    if schema is None:
        return prompt
    fields = json.dumps(schema.model_json_schema())
    return f"{prompt}\n\nAnswer with one JSON object that matches this JSON schema:\n{fields}"


# DeepEval calls DeepSeek itself, so LiteLLM's provider prefix is dropped
judge = DeepSeekJudge(
    model=(SETTINGS.get("JUDGE_MODEL") or "deepseek/deepseek-v4-pro").removeprefix("deepseek/"),
    api_key=SETTINGS["DEEPSEEK_API_KEY"],
    temperature=0,
)


def turns_of(row: dict[str, Any]) -> list[Turn]:
    tools_called = [
        ToolCall(name=call["name"], input_parameters=call["arguments"], output=call["output"]) for call in row["tools"]
    ]
    return [
        Turn(role="user", content=row["user"]),
        Turn(role="assistant", content=row["text"] or NO_TEXT, tools_called=tools_called),
    ]


def conversation_of(name: str, rows: list[dict[str, Any]]) -> ConversationalTestCase:
    expected = [turn["expect"] for turn in scenarios[name]["turns"]]
    return ConversationalTestCase(
        name=name,
        turns=[turn for row in rows for turn in turns_of(row)],
        chatbot_role=CHATBOT_ROLE,
        context=[f"The conversation took place on {transcript['played_at_local']}.", *HOW_THE_PRODUCT_WORKS],
        expectations=Expectations(
            model=judge,
            must=[
                f"In its reply to user message {row['turn']} ({row['user']!r}), the assistant does this: {expect}"
                for row, expect in zip(rows, expected, strict=True)
            ],
            must_not=NEVER,
        ),
    )


conversations = [
    conversation_of(name, list(rows)) for name, rows in groupby(transcript["turns"], key=lambda row: row["scenario"])
]
available_tools = [
    ToolCall(name=tool["name"], description=tool["description"], input_parameters=tool["parameters"])
    for tool in transcript["available_tools"]
]
reply_language = ConversationalGEval(
    name="Reply language",
    criteria=(
        "Every assistant reply is written in the language of the user message it answers (Indonesian, including "
        "casual Jakarta slang, or English). Film titles and seat ids may stay as they are. A user turn written as "
        "[pressed confirm] or [pressed cancel] is a button press, not English: the reply to it follows the user's "
        f"last written message. An assistant turn written as {NO_TEXT} has no language and is not judged."
    ),
    evaluation_params=[MultiTurnParams.ROLE, MultiTurnParams.CONTENT],
    model=judge,
)


@pytest.mark.parametrize("conversation", conversations, ids=lambda conversation: conversation.name)
def test_conversation(conversation: ConversationalTestCase) -> None:
    metrics = [RoleAdherenceMetric(model=judge), reply_language]
    # DeepEval 4.3.2 scores tool use 0 when no tool was called, also when calling none was right (the films are in
    # the agent's prompt, and a poem needs no tool). Those conversations are held to their conditions instead.
    if any(turn.tools_called for turn in conversation.turns):
        metrics.append(ToolUseMetric(available_tools=available_tools, model=judge))
    assert_test(conversation, metrics)

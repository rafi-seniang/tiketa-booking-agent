"""Reads a typed reply to a waiting booking. Only a clear yes to the booking as shown counts as approval."""

from typing import Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.features.chat.schemas import BookingSummary

READER_PROMPT = """A cinema's assistant showed the user this booking and asked them to confirm or cancel it:
{summary}

Classify the user's next message.
approve: it clearly accepts this booking as shown and asks for no change.
decline: it refuses or cancels the booking.
other: anything else, such as a question, a change to the booking, or a reply that is unclear."""


class ConfirmationReading(BaseModel):
    meaning: Literal["approve", "decline", "other"] = Field(description="What the user's message means for the booking")


class ConfirmationReader:
    def __init__(self, model: BaseChatModel) -> None:
        self._model = model.with_structured_output(ConfirmationReading, method="function_calling")

    async def approves(self, summary: BookingSummary, reply: str) -> bool:
        reading = await self._model.ainvoke(
            [SystemMessage(READER_PROMPT.format(summary=summary.model_dump_json(indent=1))), HumanMessage(reply)]
        )
        if not isinstance(reading, ConfirmationReading):
            raise TypeError(f"the confirmation reader returned {type(reading).__name__}")
        return reading.meaning == "approve"

"""Reads a typed reply to a waiting booking. Only a clear yes to the booking as shown counts as approval."""

from typing import Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.generative.prompts import READER_PROMPT
from app.schemas.chat import BookingSummary


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

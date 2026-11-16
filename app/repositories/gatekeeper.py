"""Gatekeeper, the lab's LLM gate, asked about each visitor message before the agent reads it.

The scope lives in Gatekeeper under a name, so its console shows the exact text this agent is checked against.
"""

import httpx
from pydantic import BaseModel

from app.core.errors import GateUnavailable


class GateVerdict(BaseModel):
    blocked: bool
    blocked_by: str | None = None
    decision_ms: float


class Gatekeeper:
    def __init__(self, http: httpx.AsyncClient, scope_name: str) -> None:
        self._http = http
        self._scope_name = scope_name

    async def verdict(self, text: str) -> GateVerdict:
        """Whether the message is an injection or outside the cinema. Fails loudly when the gate is down."""
        body = {"messages": [{"role": "user", "content": text}], "scope_name": self._scope_name}
        try:
            response = await self._http.post("/v1/gate/check", json=body)
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise GateUnavailable(f"Gatekeeper did not answer: {type(error).__name__}") from error
        return GateVerdict.model_validate(response.json())

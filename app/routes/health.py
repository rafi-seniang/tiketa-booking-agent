"""Liveness touches nothing (the web app polls it to show the chat On or Off). /meta describes the service."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app import VERSION
from app.core.dependencies import get_resources
from app.core.lifespan import Resources
from app.schemas.health import ServiceMeta

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/meta")
async def meta(resources: Annotated[Resources, Depends(get_resources)]) -> ServiceMeta:
    return ServiceMeta(
        id="tiketa-agent",
        name="Tiketa booking agent",
        summary="A chat agent for Tiketa: finds showtimes, picks seats, and books through the booking API after a yes.",
        version=VERSION,
        engine=resources.model_name,
        own_ui_path="/docs",
        docs_path="/docs",
    )

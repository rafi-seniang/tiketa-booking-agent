"""Liveness touches nothing (the lobby polls it). /meta describes the service for the lab frontend."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app import VERSION
from app.core.dependencies import get_resources
from app.core.lifespan import Resources
from app.features.health.schemas import ServiceMeta

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/meta")
async def meta(resources: Annotated[Resources, Depends(get_resources)]) -> ServiceMeta:
    return ServiceMeta(
        id="tiketa",
        name="Tiketa",
        summary="A cinema booking assistant: finds showtimes, picks seats, and books only after the user confirms.",
        version=VERSION,
        engine=resources.model_name,
        own_ui_path="/docs",
        docs_path="/docs",
    )

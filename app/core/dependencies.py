"""Dependency providers for the routes. Services are built once at startup, controllers per request around them.
Tests swap any of them with app.dependency_overrides."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Request

from app.controllers.bookings import BookingController
from app.controllers.catalog import CatalogController
from app.controllers.chat import ChatController
from app.core.errors import RateLimited
from app.core.lifespan import Resources
from app.middleware.rate_limit import RateLimiter, caller_of
from app.repositories.cinema import CinemaStore
from app.services.chat import ChatService
from app.settings import Settings


def get_resources(request: Request) -> Resources:
    resources: Resources = request.app.state.resources
    return resources


def get_settings(request: Request) -> Settings:
    """The settings this app instance was built with (not a global), so tests and workers can differ."""
    settings: Settings = request.app.state.settings
    return settings


def get_now() -> datetime:
    """The clock, as a dependency, so tests can fix the time a booking is made."""
    return datetime.now(UTC)


def get_rate_limiter(resources: Annotated[Resources, Depends(get_resources)]) -> RateLimiter:
    return resources.rate_limiter


async def enforce_rate_limit(
    request: Request,
    rate_limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    retry_after = await rate_limiter.hit(caller_of(request), settings.rate_limit_per_minute)
    if retry_after is not None:
        raise RateLimited(f"Over {settings.rate_limit_per_minute} requests a minute.", retry_after)


def get_store(resources: Annotated[Resources, Depends(get_resources)]) -> CinemaStore:
    """The cinema's data, shared by the catalog and the booking form."""
    return resources.store


def get_chat_service(resources: Annotated[Resources, Depends(get_resources)]) -> ChatService:
    return resources.chat


def get_chat_controller(service: Annotated[ChatService, Depends(get_chat_service)]) -> ChatController:
    return ChatController(service)


def get_catalog_controller(store: Annotated[CinemaStore, Depends(get_store)]) -> CatalogController:
    return CatalogController(store)


def get_booking_controller(
    store: Annotated[CinemaStore, Depends(get_store)], settings: Annotated[Settings, Depends(get_settings)]
) -> BookingController:
    return BookingController(store, settings.max_seats_per_booking)

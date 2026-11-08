"""The app factory: settings, logging, middleware, error handlers, then the routes."""

from fastapi import APIRouter, Depends, FastAPI

from app import VERSION
from app.core.dependencies import enforce_rate_limit
from app.core.errors import register_error_handlers
from app.core.lifespan import lifespan
from app.core.logging import configure_logging
from app.middleware.auth import require_api_key
from app.middleware.cors import add_cors
from app.middleware.request_log import register_middleware
from app.routes import bookings, catalog, chat, health
from app.settings import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(
        title="Tiketa",
        version=VERSION,
        lifespan=lifespan(settings),
        docs_url=None if settings.environment == "production" else "/docs",
    )
    app.state.settings = settings
    register_middleware(app)
    register_error_handlers(app)
    add_cors(app, settings.cors_origins)

    # Key first, then the rate limit, so an unknown caller never spends a known caller's budget
    api = APIRouter(prefix="/v1", dependencies=[Depends(require_api_key), Depends(enforce_rate_limit)])
    api.include_router(chat.router)
    api.include_router(chat.usage_router)
    api.include_router(catalog.router)
    api.include_router(bookings.router)
    app.include_router(health.router)
    app.include_router(api)
    return app

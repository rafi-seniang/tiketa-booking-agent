"""The app factory: settings, logging, middleware, error handlers, then the routes."""

import secrets

from fastapi import APIRouter, Depends, FastAPI

from app import VERSION
from app.core.dependencies import enforce_rate_limit
from app.core.errors import register_error_handlers
from app.core.lifespan import lifespan
from app.core.logging import configure_logging
from app.middleware.auth import GuestSessions, authenticate
from app.middleware.cors import add_cors
from app.middleware.request_log import register_middleware
from app.middleware.security_headers import add_security_headers
from app.routes import auth, bookings, catalog, chat, health
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
    # Without SESSION_SECRET (local only, refused in production) guest sessions end when the process does
    secret = settings.session_secret.get_secret_value() or secrets.token_urlsafe(32)
    app.state.guest_sessions = GuestSessions(secret, settings.guest_session_days)
    register_middleware(app)
    add_security_headers(app, https_only=settings.environment == "production")
    register_error_handlers(app)
    add_cors(app, settings.cors_origins)

    # Who is calling first, then the rate limit, so an unknown caller never spends a known caller's budget
    api = APIRouter(prefix="/v1", dependencies=[Depends(authenticate), Depends(enforce_rate_limit)])
    api.include_router(chat.router)
    api.include_router(chat.usage_router)
    api.include_router(catalog.router)
    api.include_router(bookings.router)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(api)
    return app

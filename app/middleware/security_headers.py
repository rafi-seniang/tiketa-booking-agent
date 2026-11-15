"""Headers on every response that tell browsers and caches what not to do with it."""

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response

PRIVATE_PATHS = ("/v1", "/auth")  # names, bookings and conversations
YEAR_SECONDS = 31_536_000


def add_security_headers(app: FastAPI, https_only: bool) -> None:
    @app.middleware("http")
    async def security_headers(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"  # a JSON body is never run as a script
        response.headers["X-Frame-Options"] = "DENY"  # no page may frame the API's pages
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith(PRIVATE_PATHS):
            response.headers["Cache-Control"] = "no-store"  # kept out of browser and proxy caches
        if https_only:
            response.headers["Strict-Transport-Security"] = f"max-age={YEAR_SECONDS}; includeSubDomains"
        return response

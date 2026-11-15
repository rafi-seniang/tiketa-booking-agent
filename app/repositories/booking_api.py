"""The booking API (tiketa-app) over HTTP. It owns films, showtimes, seats and bookings: the agent only asks.

Every call carries the credentials of the person the agent is talking to, so the agent can never do more than they
could do themselves. A refusal comes back as the same error the tools already report to the model.
"""

import hashlib
from datetime import date
from typing import Any

import httpx
from pydantic import TypeAdapter

from app.core.errors import BookingApiUnavailable, Conflict, NotFound, RateLimited, Unauthorized
from app.schemas.cinema import Booking, BookingOrder, Caller, Cinema, Movie, SeatMap, Showtime

MOVIES = TypeAdapter(list[Movie])
SHOWTIMES = TypeAdapter(list[Showtime])
BOOKINGS = TypeAdapter(list[Booking])
DEFAULT_RETRY_SECONDS = 60


def idempotency_key_of(session_id: str, tool_call_id: str) -> str:
    """One key per tool call of one conversation, at the length the API accepts whatever a provider's ids look like."""
    return hashlib.sha256(f"{session_id}:{tool_call_id}".encode()).hexdigest()


class BookingApi:
    def __init__(self, http: httpx.AsyncClient) -> None:
        self._http = http

    async def caller_name(self, credentials: dict[str, str]) -> str:
        """How the booking API names whoever holds these credentials. It refuses the ones it does not accept."""
        answer = await self._send("GET", "/v1/me", credentials)
        return str(answer["caller"])

    async def cinema(self, caller: Caller) -> Cinema:
        return Cinema.model_validate(await self._send("GET", "/v1/cinema", caller.credentials))

    async def list_movies(self, caller: Caller) -> list[Movie]:
        return MOVIES.validate_python(await self._send("GET", "/v1/movies", caller.credentials))

    async def get_movie(self, movie_id: int, caller: Caller) -> Movie:
        return Movie.model_validate(await self._send("GET", f"/v1/movies/{movie_id}", caller.credentials))

    async def showtimes_on(self, day: date, movie_id: int | None, caller: Caller) -> list[Showtime]:
        """Showtimes on one cinema-local day that have not started yet, for one film or all of them."""
        params = {"day": day.isoformat()} | ({} if movie_id is None else {"movie_id": str(movie_id)})
        return SHOWTIMES.validate_python(await self._send("GET", "/v1/showtimes", caller.credentials, params=params))

    async def get_showtime(self, showtime_id: int, caller: Caller) -> Showtime:
        return Showtime.model_validate(await self._send("GET", f"/v1/showtimes/{showtime_id}", caller.credentials))

    async def seat_map(self, showtime_id: int, caller: Caller) -> SeatMap:
        answer = await self._send("GET", f"/v1/showtimes/{showtime_id}/seats", caller.credentials)
        return SeatMap.model_validate(answer)

    async def book(self, order: BookingOrder, idempotency_key: str, caller: Caller) -> Booking:
        """Books every seat or none. Sent again with the same key, the API returns the first booking."""
        headers = {**caller.credentials, "Idempotency-Key": idempotency_key}
        return Booking.model_validate(await self._send("POST", "/v1/bookings", headers, json=order.model_dump()))

    async def bookings_of_session(self, session_id: str, caller: Caller) -> list[Booking]:
        """The bookings made in one conversation, newest first."""
        params = {"session_id": session_id}
        return BOOKINGS.validate_python(await self._send("GET", "/v1/bookings", caller.credentials, params=params))

    async def _send(self, method: str, path: str, headers: dict[str, str], **request: Any) -> Any:
        try:
            response = await self._http.request(method, path, headers=headers, **request)
        except httpx.HTTPError as failure:
            raise BookingApiUnavailable(f"The booking service did not answer ({type(failure).__name__})") from failure
        if response.is_success:
            return response.json()
        detail = refusal_of(response)
        if response.status_code == 401:
            raise Unauthorized(detail)
        if response.status_code == 404:
            raise NotFound(detail)
        if response.status_code in (409, 422):
            raise Conflict(detail)
        if response.status_code == 429:
            raise RateLimited(detail, int(response.headers.get("Retry-After", DEFAULT_RETRY_SECONDS)))
        raise BookingApiUnavailable(f"The booking service answered {response.status_code}")


def refusal_of(response: httpx.Response) -> str:
    """The API's own words for a refusal (problem+json `detail`), which the model and the user can act on."""
    try:
        detail = response.json().get("detail")
    except ValueError:
        detail = None
    return detail if isinstance(detail, str) else f"The booking service answered {response.status_code}"

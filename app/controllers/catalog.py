"""Films, a day's showtimes and a seat map, read for a UI next to the chat."""

from datetime import date, datetime

from app.repositories.cinema import CinemaStore
from app.schemas.cinema import Movie, SeatMap, Showtime


class CatalogController:
    def __init__(self, store: CinemaStore) -> None:
        self._store = store

    async def movies(self) -> list[Movie]:
        return await self._store.list_movies()

    async def showtimes(self, day: date, now: datetime, movie_id: int | None) -> list[Showtime]:
        return await self._store.showtimes_on(day, now, movie_id)

    async def seat_map(self, showtime_id: int) -> SeatMap:
        return await self._store.seat_map(showtime_id)

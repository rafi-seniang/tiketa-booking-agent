"""What a cinema UI shows next to the chat: films, a day's showtimes, a seat map. Read only."""

from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends

from app.cinema.schemas import Movie, SeatMap, Showtime
from app.cinema.store import CinemaStore
from app.platform.dependencies import get_now, get_resources
from app.platform.resources import Resources

router = APIRouter(tags=["catalog"])


def get_store(resources: Annotated[Resources, Depends(get_resources)]) -> CinemaStore:
    return resources.store


Store = Annotated[CinemaStore, Depends(get_store)]


@router.get("/movies")
async def list_movies(store: Store) -> list[Movie]:
    return await store.list_movies()


@router.get("/showtimes")
async def list_showtimes(
    day: date, store: Store, now: Annotated[datetime, Depends(get_now)], movie_id: int | None = None
) -> list[Showtime]:
    """Showtimes on a cinema-local day that have not started yet."""
    return await store.showtimes_on(day, now, movie_id)


@router.get("/showtimes/{showtime_id}/seats")
async def seat_map(showtime_id: int, store: Store) -> SeatMap:
    return await store.seat_map(showtime_id)

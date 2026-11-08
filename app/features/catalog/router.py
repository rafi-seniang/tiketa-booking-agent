"""What a cinema UI shows next to the chat: films, a day's showtimes, a seat map. Read only."""

from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.dependencies import get_now, get_store
from app.repositories.cinema import CinemaStore
from app.schemas.cinema import Movie, SeatMap, Showtime

router = APIRouter(tags=["catalog"])
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

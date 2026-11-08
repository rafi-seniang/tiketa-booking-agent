"""What a cinema UI shows next to the chat: films, a day's showtimes, a seat map. Read only."""

from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends

from app.controllers.catalog import CatalogController
from app.core.dependencies import get_catalog_controller, get_now
from app.schemas.cinema import Movie, SeatMap, Showtime

router = APIRouter(tags=["catalog"])
Controller = Annotated[CatalogController, Depends(get_catalog_controller)]


@router.get("/movies")
async def list_movies(controller: Controller) -> list[Movie]:
    return await controller.movies()


@router.get("/showtimes")
async def list_showtimes(
    day: date, controller: Controller, now: Annotated[datetime, Depends(get_now)], movie_id: int | None = None
) -> list[Showtime]:
    """Showtimes on a cinema-local day that have not started yet."""
    return await controller.showtimes(day, now, movie_id)


@router.get("/showtimes/{showtime_id}/seats")
async def seat_map(showtime_id: int, controller: Controller) -> SeatMap:
    return await controller.seat_map(showtime_id)

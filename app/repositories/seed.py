"""Sample films (Tiketa v1's list) and a schedule for the coming days. Running it again only adds what is missing."""

from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.core.database import Sessions
from app.models.cinema import MovieRow, ShowtimeRow
from app.utils.clock import local_day_window

TMDB = "https://image.tmdb.org/t/p/original"

SAMPLE_MOVIES: list[dict[str, Any]] = [
    {
        "title": "Spirited Away",
        "synopsis": "A young girl navigates a spirit world to free her parents from a mysterious curse.",
        "release_year": 2001,
        "genres": ["Animation", "Fantasy", "Family"],
        "studio_number": 1,
        "poster_url": "https://images.weserv.nl/?url=theposterdb.com/api/assets/111928/view",
        "trailer_youtube_id": "GAp2_0JJskk",
    },
    {
        "title": "Your Name",
        "synopsis": "Two teens mysteriously swap bodies and race against time to change their intertwined fate.",
        "release_year": 2016,
        "genres": ["Animation", "Drama", "Romance"],
        "studio_number": 2,
        "poster_url": "https://images.weserv.nl/?url=theposterdb.com/api/assets/90914/view",
        "trailer_youtube_id": "k4xGqY5IDBE",
    },
    {
        "title": "Akira",
        "synopsis": "Neo-Tokyo faces chaos when a teen biker unlocks a government secret with psychic power.",
        "release_year": 1988,
        "genres": ["Animation", "Action", "Science Fiction"],
        "studio_number": 3,
        "poster_url": f"{TMDB}/6pG3nVF7uWvFPCrNRBGwZqFhoQT.jpg",
        "trailer_youtube_id": "nA8KmHC2Z-g",
    },
    {
        "title": "Ghost in the Shell",
        "synopsis": "A cyborg agent hunts a hacker in a world where the line between human and machine blurs.",
        "release_year": 1995,
        "genres": ["Animation", "Science Fiction", "Thriller"],
        "studio_number": 4,
        "poster_url": "https://images.weserv.nl/?url=theposterdb.com/api/assets/98465/view",
        "trailer_youtube_id": "rU6Matng9MU",
    },
    {
        "title": "Attack on Titan: The Last Attack",
        "synopsis": "Eren leads the Rumbling across the world while his former friends try to stop him.",
        "release_year": 2024,
        "genres": ["Animation", "Action", "Drama"],
        "studio_number": 5,
        "poster_url": None,
        "trailer_youtube_id": None,
    },
    {
        "title": "Mobile Suit Gundam SEED Freedom",
        "synopsis": "Kira and the peace agency COMPASS are drawn into a war when a new nation proposes a joint strike.",
        "release_year": 2024,
        "genres": ["Animation", "Action", "Science Fiction"],
        "studio_number": 6,
        "poster_url": f"{TMDB}/1EBnttleJaKnWWyyEqfiSn76ZjT.jpg",
        "trailer_youtube_id": "Gsj6ToFTGgc",
    },
    {
        "title": "Interstellar",
        "synopsis": "Explorers travel through a wormhole in search of a new home for humanity.",
        "release_year": 2014,
        "genres": ["Adventure", "Drama", "Science Fiction"],
        "studio_number": 7,
        "poster_url": f"{TMDB}/gEU2QniE6E77NI6lCU6MxlNBvIx.jpg",
        "trailer_youtube_id": "zSWdZVtXT7E",
    },
    {
        "title": "Blade Runner 2049",
        "synopsis": "A replicant blade runner uncovers a secret that could upset the balance of humans and androids.",
        "release_year": 2017,
        "genres": ["Drama", "Science Fiction", "Thriller"],
        "studio_number": 8,
        "poster_url": f"{TMDB}/gajva2L0rPYkEWjzgFlBXCAVBE5.jpg",
        "trailer_youtube_id": "gCcx85zbxz4",
    },
    {
        "title": "Dune: Part Two",
        "synopsis": "Paul Atreides joins the Fremen to take revenge on those who destroyed his family.",
        "release_year": 2024,
        "genres": ["Adventure", "Drama", "Science Fiction"],
        "studio_number": 9,
        "poster_url": f"{TMDB}/6izwz7rsy95ARzTR3poZ8H6c5pp.jpg",
        "trailer_youtube_id": "U2Qp5pL3ovA",
    },
    {
        "title": "The Matrix",
        "synopsis": "A hacker discovers reality is a simulation and joins a rebellion to free humanity.",
        "release_year": 1999,
        "genres": ["Action", "Science Fiction"],
        "studio_number": 10,
        "poster_url": f"{TMDB}/p96dm7sCMn4VYAStA6siNz30G1r.jpg",
        "trailer_youtube_id": "vKQi3bBA1y8",
    },
    {
        "title": "Star Wars: A New Hope",
        "synopsis": "A farm boy joins the Rebel Alliance's mission to destroy the Death Star.",
        "release_year": 1977,
        "genres": ["Adventure", "Action", "Science Fiction"],
        "studio_number": 11,
        "poster_url": f"{TMDB}/2Cm0oygiJpk7tzboSvX8F86v8PW.jpg",
        "trailer_youtube_id": "vZ734NWnAHA",
    },
    {
        "title": "Mad Max: Fury Road",
        "synopsis": "Imperator Furiosa and Max flee a tyrant across a post-apocalyptic desert.",
        "release_year": 2015,
        "genres": ["Action", "Adventure", "Science Fiction"],
        "studio_number": 12,
        "poster_url": f"{TMDB}/hA2ple9q4qnwxp3hKVNhroipsir.jpg",
        "trailer_youtube_id": "hEJnMQG9ev8",
    },
    {
        "title": "Everything Everywhere All at Once",
        "synopsis": "An overwhelmed mother taps into versions of herself in other universes to save existence.",
        "release_year": 2022,
        "genres": ["Action", "Comedy", "Science Fiction"],
        "studio_number": 13,
        "poster_url": f"{TMDB}/u68AjlvlutfEIcpmbYpKcdi09ut.jpg",
        "trailer_youtube_id": "wxN1T1uxQ2g",
    },
    {
        "title": "Black Panther",
        "synopsis": "T'Challa returns to Wakanda to defend his throne and his nation's future.",
        "release_year": 2018,
        "genres": ["Action", "Adventure", "Science Fiction"],
        "studio_number": 14,
        "poster_url": f"{TMDB}/uxzzxijgPIY7slzFvMotPv8wjKA.jpg",
        "trailer_youtube_id": "xjDjIWPwcPU",
    },
    {
        "title": "The Dark Knight",
        "synopsis": "Batman faces the Joker in a battle for Gotham's soul.",
        "release_year": 2008,
        "genres": ["Action", "Crime", "Drama"],
        "studio_number": 15,
        "poster_url": f"{TMDB}/qJ2tW6WMUDux911r6m7haRef0WH.jpg",
        "trailer_youtube_id": "EXeTwQWrcwY",
    },
    {
        "title": "Inception",
        "synopsis": "A thief who steals secrets through dreams is asked to plant an idea instead.",
        "release_year": 2010,
        "genres": ["Action", "Science Fiction", "Thriller"],
        "studio_number": 16,
        "poster_url": f"{TMDB}/ljsZTbVsrQSqZgWeep2B1QiDKuh.jpg",
        "trailer_youtube_id": "YoHD9XEInc0",
    },
    {
        "title": "Pulp Fiction",
        "synopsis": "Interwoven crime stories collide in Tarantino's darkly comic classic.",
        "release_year": 1994,
        "genres": ["Crime", "Thriller"],
        "studio_number": 17,
        "poster_url": f"{TMDB}/vQWk5YBFWF4bZaofAbv0tShwBvQ.jpg",
        "trailer_youtube_id": "s7EdQ4FqbhY",
    },
    {
        "title": "Parasite",
        "synopsis": "A poor family works its way into a wealthy household, with unexpected consequences.",
        "release_year": 2019,
        "genres": ["Comedy", "Drama", "Thriller"],
        "studio_number": 18,
        "poster_url": f"{TMDB}/nMF2GX9SriEMbixRvI23KZwCs0U.jpg",
        "trailer_youtube_id": "SEUXfv87Wpk",
    },
    {
        "title": "The Lord of the Rings: The Fellowship of the Ring",
        "synopsis": "A hobbit and his allies set out to destroy a ring of ultimate evil.",
        "release_year": 2001,
        "genres": ["Adventure", "Fantasy", "Action"],
        "studio_number": 19,
        "poster_url": f"{TMDB}/6oom5QYQ2yQTMJIbnvbkBL9cHo6.jpg",
        "trailer_youtube_id": "V75dMMIW2B4",
    },
    {
        "title": "Coco",
        "synopsis": "A boy who dreams of music crosses into the Land of the Dead to find his family's story.",
        "release_year": 2017,
        "genres": ["Animation", "Adventure", "Family"],
        "studio_number": 20,
        "poster_url": f"{TMDB}/6Ryitt95xrO8KXuqRGm1fUuNwqF.jpg",
        "trailer_youtube_id": "Rvr68u6k5sI",
    },
    {
        "title": "La La Land",
        "synopsis": "A jazz pianist and an actress fall in love while chasing their dreams in Los Angeles.",
        "release_year": 2016,
        "genres": ["Comedy", "Drama", "Romance"],
        "studio_number": 21,
        "poster_url": f"{TMDB}/uDO8zWDhfWwoFdKS4fzkUJt0Rf0.jpg",
        "trailer_youtube_id": "0pdqf4P9MB8",
    },
]

# Odd studios start on the half hour, even ones half an hour later, so films do not all start together
ODD_STUDIO_START_TIMES = (time(12, 30), time(15, 15), time(18, 0), time(20, 45))
EVEN_STUDIO_START_TIMES = (time(13, 0), time(15, 45), time(18, 30), time(21, 15))
# Ticket price by weekday (Monday is 0): Monday to Thursday, Friday, then the weekend
PRICE_IDR_BY_WEEKDAY = (45_000, 45_000, 45_000, 45_000, 50_000, 60_000, 60_000)


async def seed(sessions: Sessions, first_day: date, days: int, cinema_timezone: ZoneInfo) -> tuple[int, int]:
    """Adds the sample films and their showtimes from `first_day` (local) for `days` days. Returns what was added."""
    async with sessions.begin() as db:
        known_titles = set(await db.scalars(select(MovieRow.title)))
        new_movies = [MovieRow(**movie) for movie in SAMPLE_MOVIES if movie["title"] not in known_titles]
        db.add_all(new_movies)
        await db.flush()
        movies = list(await db.scalars(select(MovieRow)))

        window_starts, _ = local_day_window(first_day, cinema_timezone)
        _, window_ends = local_day_window(first_day + timedelta(days=days - 1), cinema_timezone)
        existing = await db.execute(
            select(ShowtimeRow.movie_id, ShowtimeRow.starts_at).where(
                ShowtimeRow.starts_at >= window_starts, ShowtimeRow.starts_at < window_ends
            )
        )
        existing_keys = {(movie_id, starts_at) for movie_id, starts_at in existing}
        new_showtimes: list[ShowtimeRow] = []
        for offset in range(days):  # a one-off seed: plain loops read easiest
            day = first_day + timedelta(days=offset)
            for movie in movies:
                start_times = ODD_STUDIO_START_TIMES if movie.studio_number % 2 else EVEN_STUDIO_START_TIMES
                for start_time in start_times:
                    starts_at = datetime.combine(day, start_time, cinema_timezone).astimezone(UTC)
                    if (movie.id, starts_at) not in existing_keys:
                        price_idr = PRICE_IDR_BY_WEEKDAY[day.weekday()]
                        new_showtimes.append(ShowtimeRow(movie_id=movie.id, starts_at=starts_at, price_idr=price_idr))
        db.add_all(new_showtimes)
    return len(new_movies), len(new_showtimes)

"""Add the sample films and a schedule from today (cinema time) for --days days. Safe to run again.

Usage: alembic upgrade head && python scripts/seed.py [--days 7]
"""

import argparse
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from app.cinema.seed import seed
from app.platform.database import connect_database
from app.platform.migrations import check_schema
from config.settings import get_settings


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args()
    settings = get_settings()
    cinema_timezone = ZoneInfo(settings.cinema_timezone)
    engine, sessions = connect_database(settings.database_url.get_secret_value())
    await check_schema(engine)
    today = datetime.now(cinema_timezone).date()
    new_movies, new_showtimes = await seed(sessions, today, args.days, cinema_timezone)
    await engine.dispose()
    print(f"added {new_movies} films and {new_showtimes} showtimes from {today} for {args.days} days")


if __name__ == "__main__":
    asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)  # psycopg's async mode needs a selector loop

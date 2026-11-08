"""Cinema-local time: the window of one local day in UTC, and a moment written out as people read it."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo


def local_day_window(day: date, cinema_timezone: ZoneInfo) -> tuple[datetime, datetime]:
    """From local midnight of `day` to the next local midnight, in UTC."""
    starts = datetime.combine(day, time(0), cinema_timezone).astimezone(UTC)
    ends = datetime.combine(day + timedelta(days=1), time(0), cinema_timezone).astimezone(UTC)
    return starts, ends


def local_text(moment: datetime, cinema_timezone: ZoneInfo) -> str:
    """For example "Sunday 09 November 2026, 19:00 WIB"."""
    local = moment.astimezone(cinema_timezone)
    return f"{local:%A %d %B %Y, %H:%M} {local.tzname()}"

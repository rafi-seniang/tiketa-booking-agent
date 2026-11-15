"""Cinema-local time: a moment written out as people read it."""

from datetime import datetime
from zoneinfo import ZoneInfo


def local_text(moment: datetime, cinema_timezone: ZoneInfo) -> str:
    """For example "Sunday 09 November 2026, 19:00 WIB"."""
    local = moment.astimezone(cinema_timezone)
    return f"{local:%A %d %B %Y, %H:%M} {local.tzname()}"

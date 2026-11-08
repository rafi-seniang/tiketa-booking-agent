"""The studio layout every showtime uses, as in Tiketa v1: rows A to M, an aisle after seat 9, row K a walkway."""

ROWS_FRONT_TO_BACK = ("A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "L", "M")
SEATS_PER_ROW = 18
AISLE_AFTER_SEAT = 9
WALKWAY_BEFORE_ROW = "L"

ALL_SEAT_IDS = frozenset(f"{row}{number}" for row in ROWS_FRONT_TO_BACK for number in range(1, SEATS_PER_ROW + 1))
SEATS_PER_SHOWTIME = len(ALL_SEAT_IDS)

# What the model needs to know to place "in the middle", "by the aisle" or "next to each other" on the map
SEAT_MAP_LEGEND = (
    f"-- is a taken seat and | the only aisle, between seats {AISLE_AFTER_SEAT} and {AISLE_AFTER_SEAT + 1}. "
    f"Seats 1 and {SEATS_PER_ROW} are against the walls. Seats are next to each other when they share a row and have "
    "consecutive numbers on the same side of the aisle. The centre of the hall is rows E to H, seats 6 to 13."
)


def seat_rows() -> list[tuple[str, list[str]]]:
    """Each row with its seat ids from left to right, front row first."""
    return [(row, [f"{row}{number}" for number in range(1, SEATS_PER_ROW + 1)]) for row in ROWS_FRONT_TO_BACK]


def seat_map_text(taken_seat_ids: set[str]) -> str:
    """The seat map as the model reads it: one line per row, taken seats as --, the aisle as |."""
    lines = ["SCREEN (front)"]
    for row, seat_ids in seat_rows():  # 12 rows, built in order
        if row == WALKWAY_BEFORE_ROW:
            lines.append("(walkway)")
        shown = ["--" if seat_id in taken_seat_ids else seat_id for seat_id in seat_ids]
        left, right = shown[:AISLE_AFTER_SEAT], shown[AISLE_AFTER_SEAT:]
        lines.append(f"{' '.join(left)} | {' '.join(right)}")
    lines.append("BACK")
    return "\n".join(lines)

"""The booking API's seat map as text a model can read, with what it needs to know to choose seats on it."""

from app.schemas.cinema import SeatMap, SeatRowView


def seat_ids_of(seat_map: SeatMap) -> set[str]:
    return {seat.id for row in seat_map.rows for seat in row.seats}


def taken_seat_ids_of(seat_map: SeatMap) -> set[str]:
    return {seat.id for row in seat_map.rows for seat in row.seats if seat.is_taken}


def seat_map_legend(seat_map: SeatMap) -> str:
    """What the model needs to place "in the middle", "by the aisle" or "next to each other" on this map."""
    aisle = seat_map.aisle_after_seat
    seats_per_row = len(seat_map.rows[0].seats)
    middle_rows = seat_map.rows[len(seat_map.rows) // 3 : -(len(seat_map.rows) // 3)]
    return (
        f"-- is a taken seat and | the only aisle, between seats {aisle} and {aisle + 1}. "
        f"Seats 1 and {seats_per_row} are against the walls. Seats are next to each other when they share a row and "
        "have consecutive numbers on the same side of the aisle. "
        f"The centre of the hall is rows {middle_rows[0].row} to {middle_rows[-1].row}, "
        f"seats {aisle - 3} to {aisle + 4}."
    )


def seat_map_text(seat_map: SeatMap) -> str:
    """One line per row from the screen back, taken seats as --, the aisle as |."""

    def row_line(row: SeatRowView) -> str:
        shown = ["--" if seat.is_taken else seat.id for seat in row.seats]
        line = f"{' '.join(shown[: seat_map.aisle_after_seat])} | {' '.join(shown[seat_map.aisle_after_seat :])}"
        return f"(walkway)\n{line}" if row.row == seat_map.walkway_before_row else line

    return "\n".join(["SCREEN (front)", *(row_line(row) for row in seat_map.rows), "BACK"])

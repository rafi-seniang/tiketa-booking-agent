"""The migrations build the schema the code describes, also for a database from before the split."""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config

from app.core.migrations import ALEMBIC_INI


def alembic_config(database: Path) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database.as_posix()}")
    return config


def table_names(database: Path) -> set[str]:
    with sqlite3.connect(database) as db:
        return {name for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def test_the_migrations_build_exactly_the_tables_in_the_code(tmp_path: Path) -> None:
    database = tmp_path / "fresh.db"
    config = alembic_config(database)
    command.upgrade(config, "head")
    command.check(config)  # raises when the tables in the code and in the database differ
    assert table_names(database) == {"chat_sessions", "alembic_version"}  # the cinema's tables live elsewhere now


def test_bookings_made_before_the_form_belong_to_their_conversations_owner(tmp_path: Path) -> None:
    database = tmp_path / "old.db"
    config = alembic_config(database)
    command.upgrade(config, "0001")
    with sqlite3.connect(database) as db:
        db.execute("INSERT INTO movies VALUES (1, 'Dune', 'Spice.', 2024, '[]', 9, NULL, NULL)")
        db.execute("INSERT INTO showtimes VALUES (1, 1, '2026-11-08 11:00:00', 45000)")
        db.execute("INSERT INTO chat_sessions VALUES ('s1', 'key:key-0001', '2026-11-08 03:00:00')")
        db.execute("INSERT INTO bookings VALUES (1, 'TK1', 'call_1', 's1', 1, 'Rafi', 45000, '2026-11-08 03:00:00')")
    command.upgrade(config, "0002")
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT owner, channel FROM bookings").fetchall() == [("key:key-0001", "chat")]
    command.downgrade(config, "0001")
    command.upgrade(config, "0002")


def test_the_split_keeps_conversations_and_can_be_undone(tmp_path: Path) -> None:
    database = tmp_path / "split.db"
    config = alembic_config(database)
    command.upgrade(config, "0002")
    with sqlite3.connect(database) as db:
        db.execute("INSERT INTO chat_sessions VALUES ('s1', 'guest:abc', '2026-11-08 03:00:00')")
    command.upgrade(config, "head")
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT id, owner FROM chat_sessions").fetchall() == [("s1", "guest:abc")]
    command.downgrade(config, "0002")
    assert {"movies", "showtimes", "bookings", "booked_seats"} <= table_names(database)
    command.upgrade(config, "head")


def test_the_alembic_command_sees_every_table(tmp_path: Path) -> None:
    """In its own process, as `alembic check` runs in CI, with only what migrations/env.py imports."""
    database_url = f"sqlite+aiosqlite:///{(tmp_path / 'cli.db').as_posix()}"
    environment = {**os.environ, "DATABASE_URL": database_url}
    for command_line in (["upgrade", "head"], ["check"]):
        run = subprocess.run(
            [sys.executable, "-m", "alembic", *command_line], env=environment, capture_output=True, text=True
        )
        assert run.returncode == 0, run.stderr

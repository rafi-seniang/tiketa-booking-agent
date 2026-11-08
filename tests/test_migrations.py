"""The migrations build the schema the code describes, and carry an older database's bookings forward."""

from pathlib import Path

from alembic import command
from alembic.config import Config

from app.platform.migrations import ALEMBIC_INI


def alembic_config(database: Path) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database.as_posix()}")
    return config


def test_the_migrations_build_exactly_the_tables_in_the_code(tmp_path: Path) -> None:
    config = alembic_config(tmp_path / "fresh.db")
    command.upgrade(config, "head")
    command.check(config)  # raises when the tables in the code and in the database differ

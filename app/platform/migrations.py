"""The service never changes its own schema. It checks at startup that `alembic upgrade head` has run."""

from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import AsyncEngine

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


def code_heads() -> set[str]:
    return set(ScriptDirectory.from_config(Config(str(ALEMBIC_INI))).get_heads())


async def check_schema(engine: AsyncEngine) -> None:
    def database_heads(connection: Connection) -> set[str]:
        return set(MigrationContext.configure(connection).get_current_heads())

    async with engine.connect() as connection:
        current = await connection.run_sync(database_heads)
    needed = code_heads()
    if current != needed:
        at = ", ".join(sorted(current)) or "no revision"
        raise RuntimeError(
            f"The database is at {at}, the code needs {', '.join(sorted(needed))}: run `alembic upgrade head`"
        )

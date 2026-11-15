"""The service never changes its own schema. It checks at startup that `alembic upgrade head` has run."""

import os
from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import AsyncEngine

# Where the service runs, as the alembic command finds it: the repository root, or /home/app in the image.
# Not next to this file, which an installed package keeps in site-packages
ALEMBIC_INI = Path(os.environ.get("ALEMBIC_CONFIG", "alembic.ini")).resolve()


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

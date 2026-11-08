"""Where conversations are saved between turns: the same database as the cinema, chosen by its URL."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from sqlalchemy import make_url


@asynccontextmanager
async def open_checkpointer(database_url: str) -> AsyncIterator[BaseCheckpointSaver[Any]]:
    url = make_url(database_url)
    backend = url.get_backend_name()
    if backend == "postgresql":
        conninfo = url.set(drivername="postgresql").render_as_string(hide_password=False)
        # A pool, so turns of different conversations do not wait on one connection
        connection_settings = {"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row}
        async with AsyncConnectionPool(conninfo, kwargs=connection_settings, open=False) as pool:
            postgres_saver = AsyncPostgresSaver(pool)  # type: ignore[arg-type]
            await postgres_saver.setup()
            yield postgres_saver
    elif backend == "sqlite":
        async with AsyncSqliteSaver.from_conn_string(url.database or ":memory:") as sqlite_saver:
            yield sqlite_saver
    else:
        raise RuntimeError(f"No checkpointer for {backend} databases: use PostgreSQL or SQLite")

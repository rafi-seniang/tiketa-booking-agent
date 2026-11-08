"""Runs the migrations on the service's own async engine.

Only the service's tables are compared and migrated. LangGraph's checkpoint tables (made by the checkpointer's
`setup()`) and Phoenix's schema share the database and are left alone.
"""

import asyncio

from alembic import context
from sqlalchemy import Connection

import app.cinema.tables
import app.features.chat.session_store  # noqa: F401  the tables register on Base.metadata when imported
from app.core.database import Base, connect_database
from app.settings import get_settings

target_metadata = Base.metadata


def include_name(name: str | None, type_: str, parent_names: object) -> bool:
    return type_ != "table" or name in target_metadata.tables


def database_url() -> str:
    return context.config.get_main_option("sqlalchemy.url") or get_settings().database_url.get_secret_value()


def run_on(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_name=include_name,
        render_as_batch=True,  # SQLite changes a column by copying the table
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_online() -> None:
    engine, _ = connect_database(database_url())
    async with engine.connect() as connection:
        await connection.run_sync(run_on)
    await engine.dispose()


asyncio.run(run_online(), loop_factory=asyncio.SelectorEventLoop)  # psycopg's async mode needs a selector loop

"""Alembic for Aurora Postgres semantic DB only (pgvector)."""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from unie_cortex.config import settings
from unie_cortex.db.semantic_database import build_semantic_engine, resolve_semantic_database_url
from unie_cortex.db.semantic_models import SemanticBase

import unie_cortex.db.semantic_models  # noqa: F401

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

target_metadata = SemanticBase.metadata


def _offline_url(url: str) -> str:
    if url.startswith("postgresql+asyncpg"):
        return url.replace("postgresql+asyncpg", "postgresql+psycopg2", 1)
    return url


def run_migrations_offline() -> None:
    url = resolve_semantic_database_url(settings)
    if not url:
        raise RuntimeError("Set SEMANTIC_MEMORY_ENABLED and SEMANTIC_DATABASE_URL or SECRET_ARN")
    context.configure(
        url=_offline_url(url),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    eng = build_semantic_engine(settings)
    if eng is None:
        raise RuntimeError("Semantic database URL could not be resolved")
    async with eng.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await eng.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

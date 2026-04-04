from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from unie_cortex.config import settings


class Base(DeclarativeBase):
    pass


def _using_sqlite_filesystem() -> bool:
    if settings.use_mongodb or settings.use_aurora_dsql:
        return False
    return "sqlite" in (settings.database_url or "").lower()


async def _dsql_async_creator():  # type: ignore[no-untyped-def]
    try:
        import aurora_dsql_asyncpg as dsql
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "AURORA_DSQL_CLUSTER_HOST is set but aurora-dsql-python-connector is not installed. "
            "Install with: pip install 'aurora-dsql-python-connector[asyncpg]'"
        ) from e
    host = (settings.aurora_dsql_cluster_host or "").strip()
    kwargs: dict = {
        "host": host,
        "user": settings.aurora_dsql_user,
        "dbname": settings.aurora_dsql_dbname,
    }
    region = (settings.aurora_dsql_region or "").strip()
    if region:
        kwargs["region"] = region
    prof = (settings.aurora_dsql_aws_profile or "").strip()
    if prof:
        kwargs["profile"] = prof
    td = settings.aurora_dsql_token_duration_secs
    if td is not None:
        kwargs["token_duration_secs"] = td
    return await dsql.connect(**kwargs)


def create_async_sql_engine(**engine_kwargs):
    """
    SQLAlchemy async engine for SQLite, Postgres (DATABASE_URL), or Aurora DSQL (IAM via async_creator).
    Extra kwargs are passed to ``create_async_engine`` (e.g. ``poolclass`` for Alembic).
    """
    echo = settings.unie_cortex_env == "development"
    if settings.use_aurora_dsql:
        return create_async_engine(
            "postgresql+asyncpg://",
            echo=echo,
            async_creator=_dsql_async_creator,
            pool_pre_ping=True,
            pool_recycle=settings.aurora_dsql_pool_recycle,
            **engine_kwargs,
        )
    return create_async_engine(settings.database_url, echo=echo, **engine_kwargs)


engine = None
SessionLocal = None

if not settings.use_mongodb:
    engine = create_async_sql_engine()
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _sqlite_add_label_fact_columns(conn) -> None:
    """create_all does not ALTER existing tables; add columns from older DBs."""
    if not _using_sqlite_filesystem():
        return
    res = await conn.execute(text("PRAGMA table_info(label_facts)"))
    existing = {row[1] for row in res.fetchall()}
    alters: list[tuple[str, str]] = [
        ("sku", "VARCHAR(128)"),
        ("qty", "FLOAT"),
        ("line_amount_usd", "FLOAT"),
        ("extra", "JSON"),
    ]
    for col, typ in alters:
        if col not in existing:
            await conn.execute(text(f"ALTER TABLE label_facts ADD COLUMN {col} {typ}"))


async def _sqlite_add_task_fact_columns(conn) -> None:
    if not _using_sqlite_filesystem():
        return
    res = await conn.execute(text("PRAGMA table_info(task_facts)"))
    existing = {row[1] for row in res.fetchall()}
    for col, typ in (("sku", "VARCHAR(128)"), ("extra", "JSON")):
        if col not in existing:
            await conn.execute(text(f"ALTER TABLE task_facts ADD COLUMN {col} {typ}"))


async def _sqlite_add_engagement_network_context(conn) -> None:
    if not _using_sqlite_filesystem():
        return
    res = await conn.execute(text("PRAGMA table_info(engagements)"))
    existing = {row[1] for row in res.fetchall()}
    if "network_context" not in existing:
        await conn.execute(text("ALTER TABLE engagements ADD COLUMN network_context JSON"))


async def _sqlite_add_order_financial_fact_columns(conn) -> None:
    if not _using_sqlite_filesystem():
        return
    res = await conn.execute(text("PRAGMA table_info(order_financial_facts)"))
    existing = {row[1] for row in res.fetchall()}
    alters: list[tuple[str, str]] = [
        ("referral_fees_modeled_usd", "FLOAT"),
        ("referral_fee_bucket", "VARCHAR(64)"),
        ("referral_fee_source", "VARCHAR(64)"),
    ]
    for col, typ in alters:
        if col not in existing:
            await conn.execute(text(f"ALTER TABLE order_financial_facts ADD COLUMN {col} {typ}"))


async def init_sql_db() -> None:
    if settings.use_mongodb or engine is None:
        return
    from unie_cortex.db import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _sqlite_add_label_fact_columns(conn)
        await _sqlite_add_task_fact_columns(conn)
        await _sqlite_add_engagement_network_context(conn)
        await _sqlite_add_order_financial_fact_columns(conn)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    if SessionLocal is None:
        raise RuntimeError("SQL backend disabled; set MONGODB_URI or use get_store()")
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

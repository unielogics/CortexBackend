"""Second async engine: Aurora Postgres + pgvector (semantic brain)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from unie_cortex.db.semantic_models import SemanticBase

if TYPE_CHECKING:
    from unie_cortex.config import Settings

logger = logging.getLogger(__name__)

_semantic_url_resolved: str | None | bool = False  # False = not yet resolved
semantic_engine: AsyncEngine | None = None
SemanticSessionLocal = None


def _reset_cache_for_tests() -> None:
    global _semantic_url_resolved, semantic_engine, SemanticSessionLocal
    _semantic_url_resolved = False
    semantic_engine = None
    SemanticSessionLocal = None


def resolve_semantic_database_url(settings: Settings) -> str | None:
    """Resolve URL from env or Secrets Manager (cached per process)."""
    global _semantic_url_resolved
    if _semantic_url_resolved is not False:
        return _semantic_url_resolved if isinstance(_semantic_url_resolved, str) else None
    if not settings.semantic_brain_configured:
        _semantic_url_resolved = None
        return None
    raw = (settings.semantic_database_url or "").strip()
    if raw:
        _semantic_url_resolved = raw
        return raw
    arn = (settings.semantic_database_secret_arn or "").strip()
    if not arn:
        _semantic_url_resolved = None
        return None
    try:
        from unie_cortex.utils.aws_secrets import build_postgres_async_url_from_secret, get_secret_json

        region = (settings.semantic_database_region or settings.aws_region or "").strip() or None
        secret = get_secret_json(secret_arn=arn, region_name=region)
        url = build_postgres_async_url_from_secret(secret)
        _semantic_url_resolved = url
        logger.info("Resolved SEMANTIC_DATABASE_SECRET_ARN to async Postgres URL")
        return url
    except Exception as e:
        logger.exception("Failed to resolve semantic database secret: %s", e)
        _semantic_url_resolved = None
        return None


def build_semantic_engine(settings: Settings) -> AsyncEngine | None:
    url = resolve_semantic_database_url(settings)
    if not url:
        return None
    return create_async_engine(
        url,
        echo=settings.unie_cortex_env == "development",
        pool_pre_ping=True,
        pool_recycle=settings.semantic_pool_recycle,
    )


async def init_semantic_database(engine: AsyncEngine) -> None:
    """Create pgvector extension and tables."""
    import unie_cortex.db.semantic_models  # noqa: F401

    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(SemanticBase.metadata.create_all)


async def ping_semantic_database(engine: AsyncEngine) -> str:
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    return "ok"


def configure_semantic_from_settings(settings: Settings) -> AsyncEngine | None:
    """Build global semantic engine + session factory (called from app lifespan)."""
    global semantic_engine, SemanticSessionLocal
    eng = build_semantic_engine(settings)
    semantic_engine = eng
    if eng is not None:
        from sqlalchemy.ext.asyncio import AsyncSession

        SemanticSessionLocal = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    else:
        SemanticSessionLocal = None
    return eng

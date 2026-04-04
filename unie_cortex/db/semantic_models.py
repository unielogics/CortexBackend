"""SQLAlchemy models for Aurora Postgres + pgvector (semantic brain only)."""

from __future__ import annotations

from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class SemanticBase(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MemoryChunk(SemanticBase):
    """
    Two-layer memory: embeddable text + JSONB tags for filtering.
    Linked to ledger via stable string ids (no cross-DB FK).
    """

    __tablename__ = "memory_chunks"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_memory_chunks_idempotency"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    ledger_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    proposal_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    engagement_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content_text: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    success_tag: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

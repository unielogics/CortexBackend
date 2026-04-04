"""pgvector upsert and similarity search."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


def _vector_literal(vec: list[float]) -> str:
    return "[" + ",".join(str(float(x)) for x in vec) + "]"


@dataclass
class MemorySearchRow:
    chunk_id: str
    content_text: str
    tags: dict[str, Any] | None
    similarity: float


async def upsert_memory_chunk(
    session: AsyncSession,
    *,
    idempotency_key: str,
    tenant_id: str,
    ledger_run_id: str | None,
    proposal_id: str | None,
    engagement_id: str | None,
    source: str,
    chunk_index: int,
    content_text: str,
    tags: dict[str, Any] | None,
    embedding: list[float],
    priority: int,
    success_tag: str | None,
    content_sha256: str,
) -> None:
    chunk_id = str(uuid4())
    tags_json = json.dumps(tags) if tags is not None else "null"
    emb_lit = _vector_literal(embedding)
    await session.execute(
        text(
            """
            INSERT INTO memory_chunks (
              id, idempotency_key, tenant_id, ledger_run_id, proposal_id, engagement_id,
              source, chunk_index, content_text, tags, embedding, priority, success_tag,
              content_sha256, created_at, updated_at
            ) VALUES (
              :id, :idempotency_key, :tenant_id, :ledger_run_id, :proposal_id, :engagement_id,
              :source, :chunk_index, :content_text, CAST(:tags AS jsonb), CAST(:embedding AS vector),
              :priority, :success_tag, :content_sha256, NOW(), NOW()
            )
            ON CONFLICT (idempotency_key) DO UPDATE SET
              content_text = EXCLUDED.content_text,
              tags = EXCLUDED.tags,
              embedding = EXCLUDED.embedding,
              priority = EXCLUDED.priority,
              success_tag = EXCLUDED.success_tag,
              content_sha256 = EXCLUDED.content_sha256,
              updated_at = NOW()
            """
        ),
        {
            "id": chunk_id,
            "idempotency_key": idempotency_key,
            "tenant_id": tenant_id,
            "ledger_run_id": ledger_run_id,
            "proposal_id": proposal_id,
            "engagement_id": engagement_id,
            "source": source,
            "chunk_index": chunk_index,
            "content_text": content_text,
            "tags": tags_json,
            "embedding": emb_lit,
            "priority": priority,
            "success_tag": success_tag,
            "content_sha256": content_sha256,
        },
    )
    await session.commit()


async def search_similar(
    session: AsyncSession,
    *,
    tenant_id: str,
    query_embedding: list[float],
    top_k: int,
    min_similarity: float,
    tag_filters: dict[str, Any] | None = None,
) -> list[MemorySearchRow]:
    """Cosine similarity via pgvector (vectors normalized by OpenAI embeddings)."""
    emb_lit = _vector_literal(query_embedding)
    # Optional JSONB containment: tags @> '{"approval":"approved"}'
    tag_clause = ""
    params: dict[str, Any] = {
        "qv": emb_lit,
        "tenant_id": tenant_id,
        "min_sim": min_similarity,
        "k": top_k,
    }
    if tag_filters:
        tag_clause = " AND tags @> CAST(:tag_pat AS jsonb)"
        params["tag_pat"] = json.dumps(tag_filters)

    q = text(
        f"""
        SELECT id, content_text, tags,
               (1 - (embedding <=> CAST(:qv AS vector)))::float AS sim
        FROM memory_chunks
        WHERE tenant_id = :tenant_id
          AND embedding IS NOT NULL
          AND (1 - (embedding <=> CAST(:qv AS vector))) >= :min_sim
          {tag_clause}
        ORDER BY embedding <=> CAST(:qv AS vector)
        LIMIT :k
        """
    )
    result = await session.execute(q, params)
    rows: list[MemorySearchRow] = []
    for r in result.mappings():
        rows.append(
            MemorySearchRow(
                chunk_id=str(r["id"]),
                content_text=str(r["content_text"] or ""),
                tags=r["tags"] if isinstance(r["tags"], dict) else None,
                similarity=float(r["sim"] or 0.0),
            )
        )
    return rows

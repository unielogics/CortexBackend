"""RAG: embed query and retrieve precedent bullets (tenant-scoped)."""

from __future__ import annotations

import logging
from typing import Any

from unie_cortex.config import settings
from unie_cortex.db import semantic_database as sem_db
from unie_cortex.services.semantic_memory import embedding_policy as ep
from unie_cortex.services.semantic_memory.openai_embeddings import embed_single
from unie_cortex.services.semantic_memory.repository import search_similar

logger = logging.getLogger(__name__)


async def retrieve_rag_context(
    *,
    tenant_id: str,
    query_text: str,
    tag_filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Returns dict with:
      preamble: str to prepend to system or user message
      chunk_ids: list[str]
      similarities: list[float]
    Empty preamble when disabled or error.
    """
    out: dict[str, Any] = {"preamble": "", "chunk_ids": [], "similarities": []}
    if not settings.semantic_brain_configured or sem_db.SemanticSessionLocal is None:
        return out
    if (settings.embedding_provider or "").lower() != "openai":
        return out
    if not (settings.openai_api_key or "").strip():
        return out
    qt = ep.redact_basic_pii(query_text)
    qt = ep.truncate(qt, 8000)
    try:
        qvec = await embed_single(settings, qt)
        async with sem_db.SemanticSessionLocal() as session:
            rows = await search_similar(
                session,
                tenant_id=tenant_id,
                query_embedding=qvec,
                top_k=settings.rag_top_k,
                min_similarity=settings.rag_min_similarity,
                tag_filters=tag_filters,
            )
        if not rows:
            return out
        bullets = []
        ids = []
        sims = []
        for i, r in enumerate(rows[:8], start=1):
            line = r.content_text.replace("\n", " ").strip()
            if len(line) > 400:
                line = line[:380] + "…"
            bullets.append(f"{i}. [chunk={r.chunk_id} sim={r.similarity:.2f}] {line}")
            ids.append(r.chunk_id)
            sims.append(r.similarity)
        preamble = (
            "Relevant prior scenarios (use as analogies only; current JSON facts override):\n"
            + "\n".join(bullets)
        )
        out["preamble"] = preamble
        out["chunk_ids"] = ids
        out["similarities"] = sims
        out["tag_filters"] = tag_filters
    except Exception:
        logger.exception("RAG retrieval failed")
    return out


def rag_extra_for_invocation(rag: dict[str, Any]) -> dict[str, Any] | None:
    """Subset safe to merge into NIM extra_json."""
    if not rag.get("chunk_ids"):
        return None
    return {
        "rag_chunk_ids": rag.get("chunk_ids"),
        "rag_similarities": rag.get("similarities"),
        "rag_tag_filters": rag.get("tag_filters"),
    }

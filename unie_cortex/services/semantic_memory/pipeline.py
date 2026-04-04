"""Async embedding pipeline (bounded concurrency) after ledger writes."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from unie_cortex.config import settings
from unie_cortex.db import semantic_database as sem_db
from unie_cortex.services.semantic_memory import embedding_policy as ep
from unie_cortex.services.semantic_memory.openai_embeddings import embed_single
from unie_cortex.services.semantic_memory.repository import upsert_memory_chunk

logger = logging.getLogger(__name__)

_embed_semaphore: asyncio.Semaphore | None = None


def _sem() -> asyncio.Semaphore:
    global _embed_semaphore
    if _embed_semaphore is None:
        n = max(1, int(settings.semantic_embed_max_concurrency or 4))
        _embed_semaphore = asyncio.Semaphore(n)
    return _embed_semaphore


def queue_audit_run_embedding(
    *,
    tenant_id: str,
    run_id: str,
    engagement_id: str,
    artifact: dict[str, Any],
    narrative_text: str | None,
) -> None:
    if not settings.semantic_brain_configured or sem_db.SemanticSessionLocal is None:
        return
    if (settings.embedding_provider or "").lower() != "openai":
        logger.warning("Semantic memory: only openai embedding provider implemented")
        return
    asyncio.create_task(
        _safe_run(
            _do_audit_run_embed(
                tenant_id=tenant_id,
                run_id=run_id,
                engagement_id=engagement_id,
                artifact=artifact,
                narrative_text=narrative_text,
            )
        )
    )


def queue_proposal_decision_embedding(
    *,
    tenant_id: str,
    proposal_id: str,
    engagement_id: str | None,
    decision: str,
    note_or_reason: str | None,
    source_table: str,
) -> None:
    if not settings.semantic_brain_configured or sem_db.SemanticSessionLocal is None:
        return
    if (settings.embedding_provider or "").lower() != "openai":
        return
    asyncio.create_task(
        _safe_run(
            _do_proposal_embed(
                tenant_id=tenant_id,
                proposal_id=proposal_id,
                engagement_id=engagement_id,
                decision=decision,
                note_or_reason=note_or_reason,
                source_table=source_table,
            )
        )
    )


async def _safe_run(coro):
    try:
        await coro
    except Exception:
        logger.exception("Semantic memory background task failed")


async def _do_audit_run_embed(
    *,
    tenant_id: str,
    run_id: str,
    engagement_id: str,
    artifact: dict[str, Any],
    narrative_text: str | None,
) -> None:
    async with _sem():
        raw = json.dumps(artifact, default=str)
        raw = ep.redact_basic_pii(raw)
        raw = ep.truncate(raw, settings.semantic_embed_max_chars_audit)
        narrative = (narrative_text or "").strip()
        if narrative:
            narrative = ep.redact_basic_pii(narrative)
            narrative = ep.truncate(narrative, min(2000, settings.semantic_embed_max_chars_audit))
        blob = f"Audit run {run_id} engagement {engagement_id}.\n{narrative}\n\nFacts:\n{raw}"
        blob = ep.truncate(blob, settings.semantic_embed_max_chars_audit + 2500)
        h = ep.sha256_hex(blob)
        vec = await embed_single(settings, blob)
        idem = f"audit_run:{run_id}:0"
        tags: dict[str, Any] = {"kind": "audit_run", "engagement_id": engagement_id}
        async with sem_db.SemanticSessionLocal() as session:
            await upsert_memory_chunk(
                session,
                idempotency_key=idem,
                tenant_id=tenant_id,
                ledger_run_id=run_id,
                proposal_id=None,
                engagement_id=engagement_id,
                source="audit_artifact",
                chunk_index=0,
                content_text=blob,
                tags=tags,
                embedding=vec,
                priority=0,
                success_tag=None,
                content_sha256=h,
            )


async def _do_proposal_embed(
    *,
    tenant_id: str,
    proposal_id: str,
    engagement_id: str | None,
    decision: str,
    note_or_reason: str | None,
    source_table: str,
) -> None:
    async with _sem():
        note = (note_or_reason or "").strip()
        note = ep.redact_basic_pii(note)
        note = ep.truncate(note, settings.semantic_embed_max_chars_proposal)
        blob = (
            f"MAIW proposal {proposal_id} decision={decision} source={source_table}. "
            f"engagement_id={engagement_id or 'n/a'}.\nNote: {note}"
        )
        h = ep.sha256_hex(blob)
        vec = await embed_single(settings, blob)
        idem = f"proposal_decision:{proposal_id}:{source_table}"
        tags: dict[str, Any] = {
            "kind": "proposal_decision",
            "approval": decision,
            "proposal_id": proposal_id,
            "source_table": source_table,
        }
        if engagement_id:
            tags["engagement_id"] = engagement_id
        priority = 10 if decision == "approved" else 3
        async with sem_db.SemanticSessionLocal() as session:
            await upsert_memory_chunk(
                session,
                idempotency_key=idem,
                tenant_id=tenant_id,
                ledger_run_id=None,
                proposal_id=proposal_id,
                engagement_id=engagement_id,
                source="proposal_decision",
                chunk_index=0,
                content_text=blob,
                tags=tags,
                embedding=vec,
                priority=priority,
                success_tag=decision if decision == "approved" else None,
                content_sha256=h,
            )

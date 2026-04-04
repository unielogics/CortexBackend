"""NVIDIA NIM OpenAI-compatible chat/completions with optional AI observability persistence."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import httpx

from unie_cortex.config import Settings
from unie_cortex.db.store import CortexStore


def prompt_fingerprint(
    *,
    messages: list[dict[str, Any]],
    model: str,
    temperature: float,
    max_tokens: int,
) -> str:
    canonical = json.dumps(
        {
            "messages": messages,
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass
class NimChatOutcome:
    """Result of a single NIM chat/completions attempt (observability id unless skipped_no_key)."""

    content: str | None
    source: str
    http_status: int | None
    latency_ms: int
    ai_invocation_id: str | None = None
    raw_response_text: str | None = None


async def _maybe_persist(settings: Settings, store: CortexStore | None, *, doc: dict[str, Any]) -> None:
    if store and settings.ai_observability_enabled:
        await store.ai_invocation_insert(doc)


async def nim_post_chat_completions(
    settings: Settings,
    *,
    capability: str,
    messages: list[dict[str, Any]],
    temperature: float,
    max_tokens: int,
    store: CortexStore | None = None,
    tenant_id: str | None = None,
    engagement_id: str | None = None,
    run_id: str | None = None,
    proposal_id: str | None = None,
    correlation_id: str | None = None,
    extra: dict[str, Any] | None = None,
    rag_observability: dict[str, Any] | None = None,
    timeout_sec: float = 120,
) -> NimChatOutcome:
    """
    POST to NIM chat/completions. Missing API key => skipped_no_key with no DB write.
    Otherwise may persist AiInvocation when ``store`` is set and ``ai_observability_enabled``.
    """
    key = (settings.nvidia_api_key or "").strip()
    if not key:
        return NimChatOutcome(content=None, source="skipped_no_key", http_status=None, latency_ms=0)

    inv_id = str(uuid4())
    url = f"{settings.nim_base_url.rstrip('/')}/chat/completions"
    model = settings.nim_model
    prompt_sha = prompt_fingerprint(
        messages=messages, model=model, temperature=temperature, max_tokens=max_tokens
    )
    merged_extra: dict[str, Any] = {}
    if extra:
        merged_extra.update(extra)
    if rag_observability:
        merged_extra["rag"] = rag_observability
    extra_json = json.dumps(merged_extra, default=str) if merged_extra else None
    preview_n = int(settings.ai_observability_preview_max_chars or 0)

    def previews_for(response_body: str | None) -> tuple[str | None, str | None]:
        if preview_n <= 0:
            return None, None
        pm = json.dumps(messages, default=str)
        prompt_preview = (pm[:preview_n] if pm else None)
        response_preview = ((response_body or "")[:preview_n] or None) if response_body else None
        return prompt_preview, response_preview

    def response_sha256_from(body: str | None) -> str | None:
        if not body:
            return None
        return hashlib.sha256(body.encode("utf-8")).hexdigest()

    t0 = time.perf_counter()

    async def persist_and_return(
        *,
        content: str | None,
        source: str,
        http_status: int | None,
        response_body: str | None,
    ) -> NimChatOutcome:
        latency_ms = int((time.perf_counter() - t0) * 1000)
        pp, rp = previews_for(response_body)
        doc = {
            "id": inv_id,
            "capability": capability,
            "tenant_id": tenant_id,
            "engagement_id": engagement_id,
            "run_id": run_id,
            "proposal_id": proposal_id,
            "correlation_id": correlation_id,
            "model": model,
            "http_status": http_status,
            "latency_ms": latency_ms,
            "source": source,
            "prompt_sha256": prompt_sha,
            "response_sha256": response_sha256_from(response_body),
            "prompt_preview": pp,
            "response_preview": rp,
            "extra_json": extra_json,
        }
        await _maybe_persist(settings, store, doc=doc)
        return NimChatOutcome(
            content=content,
            source=source,
            http_status=http_status,
            latency_ms=latency_ms,
            ai_invocation_id=inv_id,
            raw_response_text=response_body,
        )

    try:
        async with httpx.AsyncClient(timeout=timeout_sec) as client:
            r = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            )
        body_text = r.text
        if r.status_code != 200:
            return await persist_and_return(
                content=None,
                source=f"error_http_{r.status_code}",
                http_status=r.status_code,
                response_body=body_text,
            )
        data = r.json()
        body_for_hash = json.dumps(data, sort_keys=True, separators=(",", ":"))
        choices = data.get("choices") or []
        content: str | None = None
        if choices:
            content = ((choices[0].get("message") or {}).get("content") or "").strip() or None
        if not content:
            return await persist_and_return(
                content=None,
                source="error_empty",
                http_status=r.status_code,
                response_body=body_for_hash,
            )
        return await persist_and_return(
            content=content,
            source="nim",
            http_status=r.status_code,
            response_body=body_for_hash,
        )
    except Exception as e:
        err_txt = str(e)
        return await persist_and_return(
            content=None,
            source=f"error_{type(e).__name__}",
            http_status=None,
            response_body=err_txt,
        )

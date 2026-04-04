"""OpenAI-compatible embedding API (httpx)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from unie_cortex.config import Settings

logger = logging.getLogger(__name__)


async def embed_texts(
    settings: Settings,
    texts: list[str],
    *,
    timeout_sec: float = 60.0,
) -> list[list[float]]:
    key = (settings.openai_api_key or "").strip()
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not set (required for EMBEDDING_PROVIDER=openai)")
    base = settings.openai_embedding_base_url.rstrip("/")
    model = settings.openai_embedding_model
    url = f"{base}/embeddings"
    out_vectors: list[list[float]] = []
    async with httpx.AsyncClient(timeout=timeout_sec) as client:
        for chunk_start in range(0, len(texts), 16):
            batch = texts[chunk_start : chunk_start + 16]
            r = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                json={"model": model, "input": batch},
            )
            r.raise_for_status()
            data = r.json()
            rows = sorted(data.get("data") or [], key=lambda x: x.get("index", 0))
            for row in rows:
                vec = row.get("embedding")
                if not isinstance(vec, list):
                    raise RuntimeError("Invalid embedding response")
                out_vectors.append([float(x) for x in vec])
    if len(out_vectors) != len(texts):
        raise RuntimeError("Embedding count mismatch")
    return out_vectors


async def embed_single(settings: Settings, text: str) -> list[float]:
    vecs = await embed_texts(settings, [text])
    return vecs[0]

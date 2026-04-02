"""Warehouse Intelligence — stub adapters for NVIDIA Multi Agent Intelligence Warehouse and cuOpt (wire real endpoints when available)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from unie_cortex.config import settings

logger = logging.getLogger(__name__)


async def call_nvidia_maiw_narrative(context: dict[str, Any], timeout_sec: float = 12.0) -> dict[str, Any] | None:
    """
    Placeholder: call enterprise MAIW / NIM when `NVIDIA_API_KEY` and optional `NVIDIA_MAIW_URL` are set.
    Returns { "text": "...", "model": "..." } or None on skip/failure.
    """
    if getattr(settings, "maiw_force_internal_only", False):
        return None
    key = getattr(settings, "nvidia_api_key", None)
    if not key:
        return None
    # Future: httpx POST to settings.nvidia_maiw_url with context
    await asyncio.sleep(0)
    return {
        "text": "NVIDIA MAIW adapter stub: configure NVIDIA_MAIW_URL for live agent reasoning.",
        "model": "stub-maiw",
    }


async def call_nvidia_cuopt_pick_sequence(
    stops: list[dict[str, Any]],
    layout: dict[str, Any] | None,
    timeout_sec: float = 20.0,
) -> dict[str, Any] | None:
    """
    Placeholder: invoke cuOpt cloud when keys present (reuse existing cuOpt settings pattern).
    Returns { "orderedStopIds": [...], "objective": float } or None.
    """
    if getattr(settings, "maiw_force_internal_only", False):
        return None
    if not (getattr(settings, "cuopt_api_key", None) or getattr(settings, "nvidia_api_key", None)):
        return None
    await asyncio.sleep(0)
    # Future: map stops + layout to cuOpt VRP / pickup-delivery job
    ids = [s.get("stopId") or s.get("stop_id") for s in stops if (s.get("stopId") or s.get("stop_id"))]
    if len(ids) < 2:
        return None
    return {
        "orderedStopIds": list(reversed(ids)),
        "objective": 0.0,
        "note": "cuOpt stub: reversed order placeholder; set CUOPT_API_KEY and implement job mapping.",
    }

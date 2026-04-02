"""Warehouse Intelligence — assemble four-variant responses with optional NVIDIA branches and timeouts."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from unie_cortex.config import settings
from unie_cortex.maiw_warehouse import engines
from unie_cortex.maiw_warehouse.nvidia_adapters import call_nvidia_cuopt_pick_sequence, call_nvidia_maiw_narrative
from unie_cortex.maiw_warehouse.schemas import (
    BatchPickPathRequest,
    DecisionVariant,
    FourVariantResponse,
    VariantProvenance,
    VariantStatus,
)

logger = logging.getLogger(__name__)


def make_variant(
    payload: dict,
    *,
    engine: str,
    status: VariantStatus = VariantStatus.ok,
    confidence: float | None = None,
    err: str | None = None,
    version: str | None = "v1",
) -> DecisionVariant:
    return DecisionVariant(
        payload=payload,
        confidence=confidence,
        provenance=VariantProvenance(engine=engine, version=version),
        status=status,
        error_detail=err,
    )


def skipped_variant(msg: str) -> DecisionVariant:
    return DecisionVariant(
        payload={},
        status=VariantStatus.skipped,
        error_detail=msg,
        provenance=None,
    )


async def _with_timeout(coro: Awaitable[Any], sec: float, label: str) -> Any:
    try:
        return await asyncio.wait_for(coro, timeout=sec)
    except TimeoutError:
        logger.warning("maiw_wh timeout: %s", label)
        return None
    except Exception as e:
        logger.warning("warehouse_intelligence error %s: %s", label, e)
        return None


async def build_pick_pathing_variants(req: BatchPickPathRequest) -> FourVariantResponse:
    orig = engines.pick_path_original(req)
    internal = engines.pick_path_internal(req)
    o = make_variant(orig, engine="wms_baseline", confidence=0.5)
    i = make_variant(internal, engine="internal_topology", confidence=0.65)

    force = getattr(settings, "maiw_force_internal_only", False)
    stops_dump = [s.model_dump(by_alias=True) for s in req.stops]
    layout_dump = req.layout.model_dump(by_alias=True) if req.layout else None

    cu = await _with_timeout(
        call_nvidia_cuopt_pick_sequence(stops_dump, layout_dump),
        20.0,
        "cuopt_pick",
    )
    nvidia_payload: dict | None = None
    if cu and cu.get("orderedStopIds"):
        nvidia_payload = {
            "orderedStopIds": cu["orderedStopIds"],
            "objective": cu.get("objective"),
            "method": "nvidia_cuopt",
        }

    if force:
        ipn = skipped_variant("MAIW_FORCE_INTERNAL_ONLY")
        nfs = skipped_variant("MAIW_FORCE_INTERNAL_ONLY")
    elif nvidia_payload is None:
        skip_msg = (
            "layout_missing_cuopt_requires_graph_coords_or_matrix"
            if req.layout is None
            else "NVIDIA cuOpt stub returned no sequence (configure keys + job mapping)"
        )
        ipn = skipped_variant(skip_msg)
        nfs = skipped_variant(skip_msg)
    else:
        merged = engines.merge_pick_orders(internal["orderedStopIds"], nvidia_payload["orderedStopIds"])
        ipn = make_variant(merged, engine="internal_plus_nvidia_cuopt", confidence=0.78)
        nfs = make_variant(nvidia_payload, engine="nvidia_cuopt", confidence=0.72)

    return FourVariantResponse(
        original=o,
        internal=i,
        internalPlusNvidia=ipn,
        nvidiaFromScratch=nfs,
    )


async def build_simple_four_variants(
    *,
    original_builder: Callable[[], dict],
    internal_builder: Callable[[], dict],
    context_for_nim: dict[str, Any],
    timeout_sec: float = 12.0,
) -> FourVariantResponse:
    """Original + internal always; NVIDIA branches = NIM / enterprise MAIW narrative overlay (stub)."""
    o = make_variant(original_builder(), engine="wms_baseline", confidence=0.5)
    inner = internal_builder()
    i = make_variant(inner, engine="internal", confidence=0.62)

    force = getattr(settings, "maiw_force_internal_only", False)
    nim = None if force else await _with_timeout(call_nvidia_maiw_narrative(context_for_nim), timeout_sec, "maiw_nim")

    if nim and nim.get("text"):
        merged = {**inner, "nvidiaNarrative": nim["text"], "nvidiaModel": nim.get("model")}
        ipn = make_variant(merged, engine="internal_plus_nvidia_maiw", confidence=0.7)
        nfs = make_variant(
            {"recommendation": nim["text"], "source": "nvidia_maiw_stub"},
            engine="nvidia_maiw",
            confidence=0.55,
        )
    else:
        msg = "MAIW_FORCE_INTERNAL_ONLY" if force else "NVIDIA MAIW skipped (no key or stub)"
        ipn = skipped_variant(msg)
        nfs = skipped_variant(msg)

    return FourVariantResponse(
        original=o,
        internal=i,
        internalPlusNvidia=ipn,
        nvidiaFromScratch=nfs,
    )

"""Optimization envelope for ``propose_routes``: metadata, fingerprints, route variants, metrics."""

from __future__ import annotations

import copy
import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from unie_cortex.config import settings
from unie_cortex.integrations.nim_chat import nim_post_chat_completions
from unie_cortex.network.tms_schemas import ProposeRoutesRequest

OPTIMIZATION_ENVELOPE_VERSION = "1"
PRIMARY_VARIANT_ID = "cortex_primary"
NVIDIA_VARIANT_ID = "nvidia_cuopt_cloud"


def _wms_ids_for_fingerprint(req: ProposeRoutesRequest) -> list[str]:
    if req.pallet_shipments:
        return sorted(s.wms_shipment_id for s in req.pallet_shipments)
    from unie_cortex.network.tms_warehouse_outbound_mocks import default_pallet_shipments

    return sorted(s.wms_shipment_id for s in default_pallet_shipments())


def fingerprint_propose_request(req: ProposeRoutesRequest) -> str:
    """SHA256 of normalized request slice (ids, trailer caps, key flags)."""
    t = req.trailer
    payload = {
        "wms_shipment_ids": _wms_ids_for_fingerprint(req),
        "driver_ids": sorted(d.driver_id for d in req.drivers),
        "trailer": {
            "max_weight_lb": t.max_weight_lb,
            "max_cube_cuft": t.max_cube_cuft,
            "max_pallet_positions": t.max_pallet_positions,
            "equipment_type": t.equipment_type,
        },
        "hos_enforced": req.hos_enforced,
        "tms_cuopt_sequencing": settings.tms_cuopt_sequencing,
        "tms_nvidia_cuopt_cloud_enabled": settings.tms_nvidia_cuopt_cloud_enabled,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_input_echo(req: ProposeRoutesRequest) -> dict[str, Any]:
    t = req.trailer
    return {
        "driver_ids": [d.driver_id for d in req.drivers],
        "wms_shipment_ids": _wms_ids_for_fingerprint(req),
        "trailer": {
            "max_weight_lb": t.max_weight_lb,
            "max_cube_cuft": t.max_cube_cuft,
            "max_pallet_positions": t.max_pallet_positions,
            "equipment_type": t.equipment_type,
        },
        "flags": {
            "tms_cuopt_sequencing": settings.tms_cuopt_sequencing,
            "hos_enforced": req.hos_enforced,
            "tms_nvidia_cuopt_cloud_enabled": settings.tms_nvidia_cuopt_cloud_enabled,
            "tms_nim_dispatch_summary_enabled": settings.tms_nim_dispatch_summary_enabled,
        },
    }


def aggregate_sequencing_metadata(routes_out: list[dict[str, Any]]) -> dict[str, Any]:
    nim_accepted = any(
        (r.get("schedule") or {}).get("source_sequence") not in (None, "heuristic")
        for r in routes_out
    )
    attempted = bool(settings.tms_cuopt_sequencing and (settings.cuopt_nim_url or "").strip())
    policy = "cuopt_nim_tms_vrp" if nim_accepted else "heuristic"
    return {
        "policy": policy,
        "cuopt_nim_attempted": attempted,
        "cuopt_nim_accepted": nim_accepted,
    }


def compute_route_metrics(routes: list[dict[str, Any]]) -> dict[str, Any]:
    total_km = 0.0
    total_drive_h = 0.0
    ftl_sum = 0.0
    sig: list[dict[str, Any]] = []
    for r in routes:
        legs = r.get("legs") or []
        total_km += sum(float(L.get("distance_km") or 0) for L in legs)
        total_drive_h += sum(float(L.get("drive_hours") or 0) for L in legs)
        eco = r.get("economics") or {}
        ftl_sum += float(eco.get("ftl_consolidated_usd") or 0)
        pu = [L.get("wms_shipment_id") for L in legs if L.get("stop_type") == "PICKUP"]
        de = [L.get("wms_shipment_id") for L in legs if L.get("stop_type") == "DELIVERY"]
        sig.append(
            {
                "driver_id": r.get("driver_id"),
                "pickup_wms_order": pu,
                "delivery_wms_order": de,
            }
        )
    return {
        "total_leg_km": round(total_km, 3),
        "total_drive_hours_est": round(total_drive_h, 4),
        "ftl_consolidated_usd_sum": round(ftl_sum, 2),
        "sequence_signature": sig,
    }


def primary_producer_from_routes(routes_out: list[dict[str, Any]]) -> str:
    for r in routes_out:
        ss = (r.get("schedule") or {}).get("source_sequence")
        if ss and str(ss).strip().lower() != "heuristic":
            return "cortex_cuopt_nim"
    return "cortex_heuristic"


def build_primary_route_variant(routes_out: list[dict[str, Any]]) -> dict[str, Any]:
    routes_copy = copy.deepcopy(routes_out)
    return {
        "variant_id": PRIMARY_VARIANT_ID,
        "role": "primary",
        "producer": primary_producer_from_routes(routes_out),
        "status": "complete",
        "status_detail": None,
        "routes": routes_copy,
        "metrics": compute_route_metrics(routes_copy),
        "diff_vs_variant_id": None,
        "delta": None,
        "external_raw": None,
    }


def build_resolution_metadata(
    req: ProposeRoutesRequest,
    routes_out: list[dict[str, Any]],
    *,
    layers_present: list[str],
) -> dict[str, Any]:
    return {
        "envelope_version": OPTIMIZATION_ENVELOPE_VERSION,
        "run_id": str(uuid.uuid4()),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "request_fingerprint": fingerprint_propose_request(req),
        "layers_present": layers_present,
        "cortex_engine": {
            "id": "tms_route_engine_v1",
            "road_matrix_provider": settings.road_matrix_provider,
            "hos_enforced": req.hos_enforced,
        },
        "sequencing": aggregate_sequencing_metadata(routes_out),
    }


def attach_delta_to_nvidia_variant(
    primary: dict[str, Any],
    nvidia: dict[str, Any],
) -> None:
    """Mutates ``nvidia`` with diff_vs_variant_id and delta vs primary metrics."""
    pm = primary.get("metrics") or {}
    nvidia["diff_vs_variant_id"] = PRIMARY_VARIANT_ID
    sol_cost = None
    ext = nvidia.get("external_raw") or {}
    if isinstance(ext, dict) and not ext.get("_truncated"):
        sr = ext.get("response", {}).get("solver_response") or ext.get("solver_response")
        if isinstance(sr, dict):
            sol_cost = sr.get("solution_cost")
    nvidia_metrics = nvidia.get("metrics") or {}
    if sol_cost is None:
        sol_cost = nvidia_metrics.get("nvidia_solver_solution_cost")
    nm_km = nvidia_metrics.get("total_leg_km")
    pm_km = pm.get("total_leg_km")
    delta_km = None
    if nm_km is not None and pm_km is not None:
        delta_km = round(float(nm_km) - float(pm_km), 3)
    nvidia["delta"] = {
        "total_leg_km_delta": delta_km,
        "cortex_primary_total_leg_km": pm_km,
        "nvidia_solver_solution_cost": sol_cost,
        "pickup_order_changes": [],
        "note": "NVIDIA variant v1 may omit full route remap; compare solver_cost to primary leg km only when both are meaningful.",
    }


async def try_nim_dispatch_summary(
    done_subset: dict[str, Any],
    *,
    store=None,
    tenant_id: str | None = None,
    engagement_id: str | None = None,
    run_id: str | None = None,
    proposal_id: str | None = None,
    correlation_id: str | None = None,
) -> dict[str, Any] | None:
    """
    Optional short NIM summary from a **small** structured subset only.
    Skips when disabled or no key.
    """
    if not settings.tms_nim_dispatch_summary_enabled:
        return None
    if not (settings.nvidia_api_key or "").strip():
        return None

    artifact = {
        "resolution_metadata": done_subset.get("resolution_metadata"),
        "route_variants_metrics": [
            {
                "variant_id": v.get("variant_id"),
                "producer": v.get("producer"),
                "status": v.get("status"),
                "metrics": v.get("metrics"),
            }
            for v in (done_subset.get("route_variants") or [])
        ],
    }
    system = (
        "You are a TMS planning assistant. Summarize ONLY the JSON facts below. "
        "Do not invent numbers. Reference variant_id and metrics fields explicitly."
    )
    user = json.dumps(artifact, default=str)[:80000]

    out = await nim_post_chat_completions(
        settings,
        capability="tms_dispatch_summary",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.2,
        max_tokens=1024,
        store=store,
        tenant_id=tenant_id,
        engagement_id=engagement_id,
        run_id=run_id,
        proposal_id=proposal_id,
        correlation_id=correlation_id,
    )
    if out.source == "skipped_no_key":
        return None
    if out.source == "nim" and out.content:
        return {
            "plain_text": out.content,
            "source": "nim",
            "sources": ["resolution_metadata", "route_variants.metrics"],
        }
    if out.source.startswith("error_http_"):
        return {
            "plain_text": None,
            "source": out.source,
            "sources": ["resolution_metadata", "route_variants.metrics"],
        }
    return {
        "plain_text": None,
        "source": out.source,
        "sources": ["resolution_metadata", "route_variants.metrics"],
    }


def try_nim_dispatch_summary_sync(done_subset: dict[str, Any]) -> dict[str, Any] | None:
    """Deprecated: use ``await try_nim_dispatch_summary`` from async code."""
    import asyncio

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(try_nim_dispatch_summary(done_subset))
    raise RuntimeError("try_nim_dispatch_summary_sync cannot be called from a running event loop; await try_nim_dispatch_summary")

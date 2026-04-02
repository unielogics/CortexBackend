"""
Tri-modal multi-DC / cuOpt snapshot for item intelligence: original inputs, baseline (no NVIDIA),
and NVIDIA-enhanced cuOpt when configured.

Does not alter allocation or landed_cost_economics unless wired separately; this block is for
visibility and future enrichment (e.g. cuOpt-suggested shares).
"""

from __future__ import annotations

from typing import Any

from unie_cortex.config import settings
from unie_cortex.integrations.nvidia_cuopt_cloud import resolve_cuopt_cloud_bearer_token
from unie_cortex.services.cuopt_scenario import run_multi_dc_scenario
from unie_cortex.services.warehouse_mock_rate_grid import resolve_warehouse_lat_lon

_US_CENTER_LAT = 39.83
_US_CENTER_LON = -98.58


def _sanitize_warehouse_snapshot(warehouses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for w in warehouses:
        wid = str(w.get("id") or "").strip()
        if not wid:
            continue
        out.append(
            {
                "id": wid,
                "postal": w.get("postal"),
                "target_share_pct": w.get("target_share_pct"),
                "lat": w.get("lat"),
                "lon": w.get("lon"),
                "pricing_profile_id": w.get("pricing_profile_id"),
            }
        )
    return out


def _build_cuopt_warehouse_rows(warehouses: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
    rows: list[dict[str, Any]] = []
    any_inferred = False
    for w in warehouses:
        wid = str(w.get("id") or "").strip()
        if not wid:
            continue
        ll = resolve_warehouse_lat_lon(w)
        if ll:
            lat, lon = ll
        else:
            lat, lon = _US_CENTER_LAT, _US_CENTER_LON
            any_inferred = True
        rows.append(
            {
                "id": wid,
                "lat": float(lat),
                "lon": float(lon),
                "daily_outbound_cuft": float(
                    w.get("daily_outbound_cuft")
                    or w.get("daily_outbound_cuft_estimate")
                    or 500.0
                ),
            }
        )
    return rows, any_inferred


def _lanes_for_cuopt(lanes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for L in lanes or []:
        fid, tid = L.get("from_id"), L.get("to_id")
        if not fid or not tid:
            continue
        out.append(
            {
                "from_id": str(fid),
                "to_id": str(tid),
                "avg_cost_per_cuft": float(L.get("avg_cost_per_cuft") or L.get("cost_per_lb") or 0.0),
                "utilization_pct": float(
                    L.get("utilization_pct") if L.get("utilization_pct") is not None else 100.0
                ),
            }
        )
    return out


async def build_item_intelligence_multi_dc_tri_modal(
    *,
    warehouses: list[dict[str, Any]],
    lanes: list[dict[str, Any]],
    hub_warehouse_id: str | None,
    include_overview: bool,
    include_nvidia_layer: bool,
) -> dict[str, Any] | None:
    if not include_overview:
        return None

    snap_wh = _sanitize_warehouse_snapshot(warehouses)
    snap_lanes = [dict(ln) for ln in (lanes or [])]
    cu_wh, coords_fallback_used = _build_cuopt_warehouse_rows(warehouses)
    cu_ln = _lanes_for_cuopt(lanes)

    if not cu_wh:
        return {
            "schema_version": "item_intelligence_multi_dc_tri_modal_v1",
            "status": "skipped",
            "message": "No warehouse nodes with ids for multi-DC preview.",
            "original_input": {
                "warehouses": snap_wh,
                "lanes": snap_lanes,
                "hub_warehouse_id": hub_warehouse_id,
            },
        }

    baseline = await run_multi_dc_scenario(cu_wh, cu_ln, allow_nvidia_enhancements=False)

    nim_ok = bool((getattr(settings, "cuopt_nim_url", None) or "").strip())
    cloud_enabled = bool(getattr(settings, "multi_dc_cuopt_cloud_enabled", False))
    bearer = bool(resolve_cuopt_cloud_bearer_token())
    cloud_ready = cloud_enabled and bearer

    settings_nvidia_on = bool(getattr(settings, "item_intelligence_nvidia_cuopt_enabled", True))
    nvidia_requested = bool(include_nvidia_layer and settings_nvidia_on)

    nvidia_block: dict[str, Any]
    if not nvidia_requested:
        nvidia_block = {
            "status": "skipped",
            "source": "disabled",
            "message": (
                "NVIDIA cuOpt layer not requested or disabled via "
                "item_intelligence_nvidia_cuopt_enabled / request flag."
            ),
        }
    elif not nim_ok and not cloud_ready:
        nvidia_block = {
            "status": "skipped",
            "source": "not_configured",
            "message": (
                "Configure CUOPT_NIM_URL (optional CUOPT_API_KEY) for custom /optimize, or "
                "MULTI_DC_CUOPT_CLOUD_ENABLED=true with CUOPT_API_KEY or NVIDIA_API_KEY for managed cloud."
            ),
        }
    else:
        nvidia_block = await run_multi_dc_scenario(cu_wh, cu_ln, allow_nvidia_enhancements=True)

    return {
        "schema_version": "item_intelligence_multi_dc_tri_modal_v1",
        "original_input": {
            "warehouses": snap_wh,
            "lanes": snap_lanes,
            "hub_warehouse_id": hub_warehouse_id,
        },
        "baseline_without_nvidia": baseline,
        "nvidia_enhanced": nvidia_block,
        "eligibility": {
            "item_intelligence_cuopt_overview_enabled": True,
            "item_intelligence_nvidia_cuopt_enabled": settings_nvidia_on,
            "request_include_nvidia_layer": bool(include_nvidia_layer),
            "cuopt_nim_configured": nim_ok,
            "multi_dc_cuopt_cloud_enabled": cloud_enabled,
            "cuopt_cloud_bearer_resolved": bearer,
            "warehouse_count_for_preview": len(cu_wh),
            "coords_fallback_us_center_used": coords_fallback_used,
        },
        "note": (
            "original_input is the effective network snapshot for this run. baseline_without_nvidia is always the "
            "internal lane-utilization heuristic (no NVIDIA HTTP). nvidia_enhanced runs cuOpt NIM or NVIDIA managed "
            "cloud when configured; otherwise skipped with a reason. Allocation and landed_cost_economics are computed "
            "independently unless you later wire cuOpt outputs into shares."
        ),
    }

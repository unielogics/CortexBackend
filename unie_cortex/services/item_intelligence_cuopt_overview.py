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
from unie_cortex.services.cuopt_enrichment_analysis import (
    approximate_waterfall_bridge,
    client_policy_placeholder,
    demand_band_integer_demands,
    external_integration_placeholders,
    fulfillment_executed_vs_multi_hint,
    fusion_inputs_fingerprint,
    parcel_sensitivity_rows,
)
from unie_cortex.services.cuopt_intelligence_fusion import (
    enrich_cuopt_warehouse_rows,
    fulfillment_monthly_usd_proxy_by_warehouse,
    inbound_receive_monthly_usd_by_warehouse,
    mean_mock_parcel_usd_by_warehouse,
    merge_parcel_overrides,
    monthly_allocated_cuft_by_warehouse,
    network_max_cube_cuft,
    network_max_weight_lb,
    sku_to_cube_cuft_map,
    storage_monthly_usd_by_warehouse,
)
from unie_cortex.services.cuopt_scenario import (
    _apply_fused_operating_costs_to_matrix,
    run_multi_dc_scenario,
)
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


def _serialize_solver_row(row: dict[str, Any]) -> dict[str, Any]:
    """Stable JSON snapshot of fields that affect cuOpt (original vs enhanced compare)."""
    out: dict[str, Any] = {
        "id": row.get("id"),
        "lat": row.get("lat"),
        "lon": row.get("lon"),
        "daily_outbound_cuft": row.get("daily_outbound_cuft"),
    }
    if row.get("allocated_monthly_cuft") is not None:
        out["allocated_monthly_cuft"] = round(float(row["allocated_monthly_cuft"]), 6)
    if row.get("mean_mock_parcel_usd") is not None:
        out["mean_mock_parcel_usd"] = round(float(row["mean_mock_parcel_usd"]), 6)
    if row.get("fulfillment_monthly_usd_proxy") is not None:
        out["fulfillment_monthly_usd_proxy"] = round(float(row["fulfillment_monthly_usd_proxy"]), 6)
    if row.get("storage_monthly_usd_proxy") is not None:
        out["storage_monthly_usd_proxy"] = round(float(row["storage_monthly_usd_proxy"]), 6)
    if row.get("inbound_receive_monthly_usd_proxy") is not None:
        out["inbound_receive_monthly_usd_proxy"] = round(float(row["inbound_receive_monthly_usd_proxy"]), 6)
    if row.get("network_max_cube_cuft") is not None:
        out["network_max_cube_cuft"] = round(float(row["network_max_cube_cuft"]), 6)
    if row.get("network_max_weight_lb") is not None:
        out["network_max_weight_lb"] = round(float(row["network_max_weight_lb"]), 6)
    return out


def matrix_extensions_from_cuopt_enrichment_request(
    cuopt_enrichment: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not cuopt_enrichment:
        return None
    forbidden = cuopt_enrichment.get("forbidden_directed_arcs") or []
    legs = cuopt_enrichment.get("linehaul_monthly_usd_legs") or []
    norm_f: list[dict[str, Any]] = []
    for a in forbidden:
        if not isinstance(a, dict):
            continue
        fi = str(a.get("from_warehouse_id") or a.get("from_id") or "").strip()
        ti = str(a.get("to_warehouse_id") or a.get("to_id") or "").strip()
        if fi and ti:
            norm_f.append({"from_warehouse_id": fi, "to_warehouse_id": ti})
    norm_l: list[dict[str, Any]] = []
    for leg in legs:
        if not isinstance(leg, dict):
            continue
        fi = str(leg.get("from_warehouse_id") or leg.get("from_id") or "").strip()
        ti = str(leg.get("to_warehouse_id") or leg.get("to_id") or "").strip()
        try:
            usd = float(leg.get("monthly_usd") or 0.0)
        except (TypeError, ValueError):
            usd = 0.0
        if fi and ti and usd >= 0:
            norm_l.append({"from_warehouse_id": fi, "to_warehouse_id": ti, "monthly_usd": usd})
    if not norm_f and not norm_l:
        return None
    return {"forbidden_directed_arcs": norm_f, "linehaul_monthly_usd_legs": norm_l}


def _per_destination_fusion_from_rows(warehouses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mirror fusion adds without building a full matrix (for sensitivity when NVIDIA did not return microscopic)."""
    n = len(warehouses)
    if n == 0:
        return []
    z = [[0.0] * n for _ in range(n)]
    meta = _apply_fused_operating_costs_to_matrix(z, warehouses)
    return list(meta.get("per_destination_fusion_arc_add") or [])


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
    solver_network_source: str | None = None,
    allocation: dict[str, Any] | None = None,
    placement_mock_rate_grids: dict[str, Any] | None = None,
    landed_cost_economics: dict[str, Any] | None = None,
    alloc_inputs: list[dict[str, Any]] | None = None,
    cuopt_enrichment: dict[str, Any] | None = None,
    monthly_catalog_demand_total: float | None = None,
    fulfillment_network_comparison: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not include_overview:
        return None

    snap_wh = _sanitize_warehouse_snapshot(warehouses)
    snap_lanes = [dict(ln) for ln in (lanes or [])]
    cu_wh, coords_fallback_used = _build_cuopt_warehouse_rows(warehouses)
    cu_ln = _lanes_for_cuopt(lanes)
    cu_wh_original: list[dict[str, Any]] = [dict(r) for r in cu_wh]

    fusion_meta: dict[str, Any] = {}
    cuopt_fusion_audit: dict[str, Any] | None = None
    parcel_override_meta: dict[str, Any] = {}
    mc: dict[str, float] = {}
    mp: dict[str, float] = {}
    fo: dict[str, float] = {}
    st: dict[str, float] = {}
    ib: dict[str, float] = {}
    sku_cube: dict[str, float] = {}
    ce = cuopt_enrichment if isinstance(cuopt_enrichment, dict) else None
    matrix_extensions = matrix_extensions_from_cuopt_enrichment_request(ce)
    fusion_sources = (
        allocation is not None or placement_mock_rate_grids is not None or landed_cost_economics is not None
    )
    ce_parcel_only = bool(
        ce
        and (
            isinstance(ce.get("parcel_usd_by_warehouse_id"), dict)
            or isinstance(ce.get("observed_label_buy_usd_by_warehouse_id"), dict)
        )
    )
    if fusion_sources or ce_parcel_only:
        sku_cube = sku_to_cube_cuft_map(alloc_inputs)
        mc = monthly_allocated_cuft_by_warehouse(allocation, sku_cube) if fusion_sources else {}
        if ce:
            try:
                seas = float(ce.get("demand_seasonality_index") or 1.0)
            except (TypeError, ValueError):
                seas = 1.0
            if seas > 0 and seas != 1.0 and mc:
                mc = {k: v * seas for k, v in mc.items()}
        mp = mean_mock_parcel_usd_by_warehouse(placement_mock_rate_grids) if fusion_sources else {}
        po = ce.get("parcel_usd_by_warehouse_id") if ce else None
        ol = ce.get("observed_label_buy_usd_by_warehouse_id") if ce else None
        if isinstance(po, dict) or isinstance(ol, dict):
            mp, parcel_override_meta = merge_parcel_overrides(
                mp, po if isinstance(po, dict) else None, observed_label_usd=ol if isinstance(ol, dict) else None
            )
        fo = fulfillment_monthly_usd_proxy_by_warehouse(landed_cost_economics) if fusion_sources else {}
        st = storage_monthly_usd_by_warehouse(landed_cost_economics) if fusion_sources else {}
        ib = inbound_receive_monthly_usd_by_warehouse(landed_cost_economics) if fusion_sources else {}
        n_cube = network_max_cube_cuft(alloc_inputs)
        n_wt = network_max_weight_lb(alloc_inputs)
        cu_wh, fusion_meta = enrich_cuopt_warehouse_rows(
            cu_wh,
            monthly_cuft_by_wh=mc,
            parcel_usd_by_wh=mp,
            fulfillment_monthly_usd_by_wh=fo,
            storage_monthly_usd_by_wh=st,
            inbound_monthly_usd_by_wh=ib,
            network_max_cube=n_cube if n_cube > 0 else None,
            network_max_weight_lb_val=n_wt if n_wt > 0 else None,
        )
        cuopt_fusion_audit = {
            "schema_version": "cuopt_fusion_audit_v1",
            "monthly_allocated_cuft_by_warehouse_id": mc,
            "mean_mock_parcel_usd_by_warehouse_id": mp,
            "fulfillment_monthly_usd_proxy_by_warehouse_id": fo,
            "storage_monthly_usd_proxy_by_warehouse_id": st,
            "inbound_receive_monthly_usd_proxy_by_warehouse_id": ib,
            "sku_cube_cuft_by_sku": sku_cube,
            "enrichment_row_counts": fusion_meta,
            **({"parcel_override_request_meta": parcel_override_meta} if parcel_override_meta else {}),
        }

    if not cu_wh:
        skipped: dict[str, Any] = {
            "schema_version": "item_intelligence_multi_dc_tri_modal_v1",
            "status": "skipped",
            "message": "No warehouse nodes with ids for multi-DC preview.",
            "original_input": {
                "warehouses": snap_wh,
                "lanes": snap_lanes,
                "hub_warehouse_id": hub_warehouse_id,
            },
        }
        if solver_network_source:
            skipped["cuopt_solver_network_source"] = solver_network_source
        if fusion_meta:
            skipped["cuopt_intelligence_fusion"] = fusion_meta
        if cuopt_fusion_audit:
            skipped["cuopt_fusion_audit"] = cuopt_fusion_audit
        skipped["solver_inputs_original_vs_enhanced"] = {
            "schema_version": "cuopt_solver_input_compare_v1",
            "lanes_normalized_for_solver": cu_ln,
            "original_solver_warehouse_rows": [_serialize_solver_row(r) for r in cu_wh_original],
            "enhanced_solver_warehouse_rows": [_serialize_solver_row(r) for r in cu_wh],
            "note": (
                "original = pre-placement fusion (geo + daily_outbound_cuft only). enhanced = adds "
                "allocated_monthly_cuft, mean_mock_parcel_usd, fulfillment_monthly_usd_proxy when audit inputs exist."
            ),
        }
        return skipped

    baseline = await run_multi_dc_scenario(
        cu_wh,
        cu_ln,
        allow_nvidia_enhancements=False,
        depot_warehouse_id=hub_warehouse_id,
        matrix_extensions=matrix_extensions,
    )

    self_hosted_ok = bool((getattr(settings, "cuopt_self_hosted_url", None) or "").strip())
    nim_ok = bool((getattr(settings, "cuopt_nim_url", None) or "").strip()) or self_hosted_ok
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
                "Configure CUOPT_SELF_HOSTED_URL (self-hosted REST), or CUOPT_NIM_URL + /optimize, or "
                "MULTI_DC_CUOPT_CLOUD_ENABLED=true with CUOPT_API_KEY or NVIDIA_API_KEY for managed cloud."
            ),
        }
    else:
        nvidia_block = await run_multi_dc_scenario(
            cu_wh,
            cu_ln,
            allow_nvidia_enhancements=True,
            depot_warehouse_id=hub_warehouse_id,
            matrix_extensions=matrix_extensions,
        )

    solver_compare: dict[str, Any] = {
        "schema_version": "cuopt_solver_input_compare_v1",
        "lanes_normalized_for_solver": cu_ln,
        "original_solver_warehouse_rows": [_serialize_solver_row(r) for r in cu_wh_original],
        "enhanced_solver_warehouse_rows": [_serialize_solver_row(r) for r in cu_wh],
        "note": (
            "original_solver_warehouse_rows = before placement/allocation fusion. enhanced_solver_warehouse_rows = "
            "same nodes with allocated_monthly_cuft, mock parcel, and fulfillment monthly proxies when inputs were "
            "passed. Both are used to build the NVIDIA payload (enhanced); baseline_without_nvidia uses the same "
            "enhanced rows for lane heuristic only."
        ),
    }

    nv_sis = nvidia_block.get("solver_input_summary") if isinstance(nvidia_block, dict) else None
    microscopic: dict[str, Any] = {
        "schema_version": "microscopic_placement_expenses_v1",
        "fusion_audit": cuopt_fusion_audit,
        "nvidia_solver_microscopic": (nv_sis or {}).get("microscopic_expense_basis")
        if isinstance(nv_sis, dict) and str(nvidia_block.get("status") or "") == "complete"
        else None,
        "note": (
            "fusion_audit = raw maps from allocation, placement grids, and landed economics. "
            "nvidia_solver_microscopic = per-destination fusion adds, task demand signals, and arc cost samples "
            "(when NVIDIA solve completed)."
        ),
    }

    mb = (
        ((nv_sis or {}).get("microscopic_expense_basis") or {})
        if isinstance(nv_sis, dict) and str(nvidia_block.get("status") or "") == "complete"
        else {}
    )
    per_d = mb.get("per_destination_fusion_arc_add") if isinstance(mb, dict) else None
    if not per_d:
        per_d = _per_destination_fusion_from_rows(cu_wh)
    n_wh = len(cu_wh)
    task_locs_band = [1] if n_wh == 2 else list(range(1, n_wh))
    low_m = 0.85
    high_m = 1.15
    if ce:
        try:
            if ce.get("demand_band_low_multiplier") is not None:
                low_m = float(ce["demand_band_low_multiplier"])
        except (TypeError, ValueError):
            pass
        try:
            if ce.get("demand_band_high_multiplier") is not None:
                high_m = float(ce["demand_band_high_multiplier"])
        except (TypeError, ValueError):
            pass
    low_m = min(2.0, max(0.05, low_m))
    high_m = min(3.0, max(0.05, high_m))
    fbm_ref: float | None = None
    fnc = fulfillment_network_comparison if isinstance(fulfillment_network_comparison, dict) else None
    if fnc:
        ps = fnc.get("per_sku")
        if isinstance(ps, list) and ps and isinstance(ps[0], dict):
            try:
                v = float(ps[0].get("multi_dc_recommended_fully_loaded_usd_per_unit") or 0.0)
            except (TypeError, ValueError):
                v = 0.0
            if v > 0:
                fbm_ref = v
    mc_units = float(monthly_catalog_demand_total or 0.0)
    if mc_units <= 0 and isinstance(landed_cost_economics, dict):
        for row in (landed_cost_economics.get("per_sku") or [])[:5]:
            if isinstance(row, dict):
                try:
                    mc_units += float(row.get("monthly_demand_units") or 0.0)
                except (TypeError, ValueError):
                    pass
    mc_units = max(mc_units, 1.0)

    sens_pct = None
    if ce and ce.get("parcel_sensitivity_pct") is not None:
        try:
            sens_pct = float(ce["parcel_sensitivity_pct"])
        except (TypeError, ValueError):
            sens_pct = None

    cuopt_enrichment_analysis: dict[str, Any] = {
        "schema_version": "cuopt_enrichment_analysis_v1",
        "cuopt_fusion_inputs_fingerprint_sha256": fusion_inputs_fingerprint(
            monthly_cuft=mc,
            parcel=mp,
            fulfillment=fo,
            storage=st,
            inbound=ib,
            sku_cube=sku_cube,
        ),
        "parcel_rate_sensitivity": parcel_sensitivity_rows(
            per_d if isinstance(per_d, list) else None,
            pct=sens_pct,
        ),
        "demand_band_hypothetical_integer_demands": demand_band_integer_demands(
            cu_wh, task_locs_band, low_mult=low_m, high_mult=high_m
        ),
        "waterfall_bridge": approximate_waterfall_bridge(
            microscopic_basis={"per_destination_fusion_arc_add": per_d} if per_d else None,
            monthly_catalog_units=mc_units,
            fully_loaded_fbm_multi_usd_per_u=fbm_ref,
        ),
        "external_integration_echo": external_integration_placeholders(),
        "fulfillment_executed_vs_multi_hint": fulfillment_executed_vs_multi_hint(fnc),
        "client_policy_extensions": client_policy_placeholder(
            forbidden_arc_count=len(matrix_extensions.get("forbidden_directed_arcs", []))
            if matrix_extensions
            else 0,
            linehaul_leg_count=len(matrix_extensions.get("linehaul_monthly_usd_legs", []))
            if matrix_extensions
            else 0,
        ),
    }

    return {
        "schema_version": "item_intelligence_multi_dc_tri_modal_v1",
        "original_input": {
            "warehouses": snap_wh,
            "lanes": snap_lanes,
            "hub_warehouse_id": hub_warehouse_id,
        },
        "solver_inputs_original_vs_enhanced": solver_compare,
        "microscopic_placement_expenses": microscopic,
        "cuopt_enrichment_analysis": cuopt_enrichment_analysis,
        **({"cuopt_fusion_audit": cuopt_fusion_audit} if cuopt_fusion_audit else {}),
        "baseline_without_nvidia": baseline,
        "nvidia_enhanced": nvidia_block,
        "eligibility": {
            "item_intelligence_cuopt_overview_enabled": True,
            "item_intelligence_nvidia_cuopt_enabled": settings_nvidia_on,
            "request_include_nvidia_layer": bool(include_nvidia_layer),
            "cuopt_self_hosted_configured": self_hosted_ok,
            "cuopt_nim_configured": nim_ok,
            "multi_dc_cuopt_cloud_enabled": cloud_enabled,
            "cuopt_cloud_bearer_resolved": bearer,
            "warehouse_count_for_preview": len(cu_wh),
            "coords_fallback_us_center_used": coords_fallback_used,
            **(
                {"cuopt_solver_network_source": solver_network_source}
                if solver_network_source
                else {}
            ),
            **(
                {"cuopt_enrichment_matrix_extensions": matrix_extensions}
                if matrix_extensions
                else {}
            ),
        },
        **({"cuopt_intelligence_fusion": fusion_meta} if fusion_meta else {}),
        "note": (
            "original_input = UI/network snapshot (ids, postal, shares). solver_inputs_original_vs_enhanced compares "
            "pre-fusion vs post-fusion solver rows (what changed before NVIDIA). microscopic_placement_expenses "
            "audits allocation/grid/economics maps and, when the solve completes, arc-level and task-level expense "
            "inputs in solver_input_summary.microscopic_expense_basis. baseline_without_nvidia is the internal "
            "heuristic; nvidia_enhanced is the managed/self-hosted solve."
        ),
    }

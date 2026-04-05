"""
Post-process cuOpt enrichment: fingerprints, sensitivity (no extra NVIDIA calls), waterfall hints,
external-integration placeholders, executed vs multi-DC comparison echo.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from unie_cortex.config import settings


def fusion_inputs_fingerprint(
    *,
    monthly_cuft: dict[str, float],
    parcel: dict[str, float],
    fulfillment: dict[str, float],
    storage: dict[str, float] | None,
    inbound: dict[str, float] | None,
    sku_cube: dict[str, float],
) -> str:
    payload = {
        "mc": monthly_cuft,
        "mp": parcel,
        "ff": fulfillment,
        "st": storage or {},
        "ib": inbound or {},
        "cube": sku_cube,
    }
    raw = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode()).hexdigest()


def parcel_sensitivity_rows(
    per_destination: list[dict[str, Any]] | None,
    *,
    pct: float | None = None,
) -> dict[str, Any]:
    """
    Recompute fusion add if mean parcel moved ±pct% (linear on last-mile component only).
    Does not re-call NVIDIA.
    """
    p = float(pct if pct is not None else getattr(settings, "cuopt_sensitivity_parcel_pct", 10.0) or 10.0)
    p = min(50.0, max(0.0, p))
    factor_hi = 1.0 + p / 100.0
    factor_lo = max(0.0, 1.0 - p / 100.0)
    if not per_destination:
        return {
            "schema_version": "cuopt_parcel_sensitivity_v1",
            "parcel_pct": p,
            "note": "No per_destination_fusion_arc_add — sensitivity not computed.",
            "stressed_destinations": [],
        }
    rows_hi: list[dict[str, Any]] = []
    rows_lo: list[dict[str, Any]] = []
    for row in per_destination:
        lm = float(row.get("last_mile_proxy_added_to_each_incoming_arc") or 0.0)
        ox = float(row.get("fulfillment_opex_proxy_added_to_each_incoming_arc") or 0.0)
        st = float(row.get("storage_proxy_added_to_each_incoming_arc") or 0.0)
        ib = float(row.get("inbound_proxy_added_to_each_incoming_arc") or 0.0)
        base_tot = float(row.get("total_fusion_add_to_each_incoming_arc") or 0.0)
        hi = lm * factor_hi + ox + st + ib
        lo = lm * factor_lo + ox + st + ib
        wid = row.get("warehouse_id")
        rows_hi.append(
            {
                "warehouse_id": wid,
                "total_fusion_add_stressed": round(hi, 6),
                "delta_vs_base": round(hi - base_tot, 6),
            }
        )
        rows_lo.append(
            {
                "warehouse_id": wid,
                "total_fusion_add_stressed": round(lo, 6),
                "delta_vs_base": round(lo - base_tot, 6),
            }
        )
    return {
        "schema_version": "cuopt_parcel_sensitivity_v1",
        "parcel_pct": p,
        "interpretation": (
            "Stresses only last_mile_proxy component; fulfillment/storage/inbound proxies held flat. "
            "Compare to total_fusion_add_to_each_incoming_arc in microscopic_expense_basis."
        ),
        "parcel_up": rows_hi,
        "parcel_down": rows_lo,
    }


def demand_band_integer_demands(
    warehouses: list[dict[str, Any]],
    task_locs: list[int],
    *,
    low_mult: float,
    high_mult: float,
) -> dict[str, Any]:
    """Hypothetical integer demands if allocated_monthly_cuft scaled (no API)."""
    from unie_cortex.services.cuopt_scenario import _task_demands_from_warehouses

    def _scaled_rows(mult: float) -> list[dict[str, Any]]:
        tmp: list[dict[str, Any]] = []
        for w in warehouses:
            d = dict(w)
            ac = d.get("allocated_monthly_cuft")
            if ac is not None and float(ac) > 0:
                d["allocated_monthly_cuft"] = float(ac) * mult
            tmp.append(d)
        return tmp

    lo = _task_demands_from_warehouses(_scaled_rows(low_mult), task_locs)
    hi = _task_demands_from_warehouses(_scaled_rows(high_mult), task_locs)
    mid = _task_demands_from_warehouses(warehouses, task_locs)
    return {
        "schema_version": "cuopt_demand_band_hypotheticals_v1",
        "low_multiplier": low_mult,
        "high_multiplier": high_mult,
        "integer_demands_mid": mid,
        "integer_demands_low": lo,
        "integer_demands_high": hi,
        "note": "What-if demand scaling on allocated_monthly_cuft only; mid = actual solver input.",
    }


def approximate_waterfall_bridge(
    *,
    microscopic_basis: dict[str, Any] | None,
    monthly_catalog_units: float,
    fully_loaded_fbm_multi_usd_per_u: float | None,
) -> dict[str, Any]:
    """
    Rough bridge: mean fusion add → not dollars — label as matrix stress index / unit heuristic.
    """
    if not microscopic_basis:
        return {"schema_version": "cuopt_waterfall_bridge_v1", "status": "absent"}
    per_d = microscopic_basis.get("per_destination_fusion_arc_add") or []
    if not per_d:
        return {"schema_version": "cuopt_waterfall_bridge_v1", "status": "no_fusion_breakdown"}
    totals = [float(x.get("total_fusion_add_to_each_incoming_arc") or 0.0) for x in per_d]
    avg_add = sum(totals) / len(totals) if totals else 0.0
    mu = max(1.0, float(monthly_catalog_units or 0.0))
    rough_index_per_unit = round(avg_add / mu, 8)
    out: dict[str, Any] = {
        "schema_version": "cuopt_waterfall_bridge_v1",
        "mean_destination_fusion_add_matrix_units": round(avg_add, 6),
        "monthly_catalog_units_basis": mu,
        "heuristic_fusion_stress_index_per_monthly_unit": rough_index_per_unit,
        "note": (
            "fusion adds are in the same synthetic scale as the cost matrix (not USD). "
            "Divide by monthly units for a crude intensity index; compare directionally to FBM fully loaded $/u."
        ),
    }
    if fully_loaded_fbm_multi_usd_per_u is not None and fully_loaded_fbm_multi_usd_per_u > 0:
        out["fully_loaded_fbm_multi_usd_per_unit_reference"] = round(float(fully_loaded_fbm_multi_usd_per_u), 6)
    return out


def external_integration_placeholders() -> dict[str, Any]:
    """Surface which external services are configured (no secrets)."""
    return {
        "schema_version": "cuopt_external_integration_placeholders_v1",
        "rate_shopping_url_configured": bool((getattr(settings, "rate_shopping_url", None) or "").strip()),
        "shippo_configured": bool((getattr(settings, "shippo_api_key", None) or "").strip()),
        "note": (
            "Live carrier quotes can replace parcel_usd_by_warehouse_id on the request body when you wire "
            "rate-shop results; Shippo/rate_shopping_url indicate server-side quote capability."
        ),
    }


def fulfillment_executed_vs_multi_hint(fulfillment_network_comparison: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(fulfillment_network_comparison, dict):
        return None
    ps = fulfillment_network_comparison.get("per_sku")
    if not isinstance(ps, list) or not ps:
        return {
            "schema_version": "cuopt_fbm_single_vs_multi_hint_v1",
            "status": "absent",
            "note": "No fulfillment_network_comparison.per_sku on this run.",
        }
    row0 = ps[0] if isinstance(ps[0], dict) else {}
    ex = row0.get("executed_network_fully_loaded_usd_per_unit")
    mu = row0.get("multi_dc_recommended_fully_loaded_usd_per_unit")
    return {
        "schema_version": "cuopt_fbm_single_vs_multi_hint_v1",
        "executed_fully_loaded_usd_per_unit": ex,
        "multi_dc_recommended_fully_loaded_usd_per_unit": mu,
        "note": "Echo from fulfillment_network_comparison for UI; cuOpt still requires ≥2 nodes to optimize.",
    }


def client_policy_placeholder(
    *,
    forbidden_arc_count: int,
    linehaul_leg_count: int,
) -> dict[str, Any]:
    return {
        "schema_version": "cuopt_client_policy_extensions_v1",
        "forbidden_directed_arcs_applied": forbidden_arc_count,
        "linehaul_monthly_leg_overrides_applied": linehaul_leg_count,
        "future": (
            "Hazmat SKU flags, max_active_nodes, and regional preferences can extend this block when productized."
        ),
    }

"""
Green last-mile + positioning impact for item intelligence (single-hub vs multi-routed).

Uses the same 48-state hub destinations and demand shares as ``placement_mock_rate_grids``,
geodesic ZIP5 miles (``transport_geo.geodesic_miles_zip5``), and illustrative CO₂e factors
aligned with ``transport_miles_v1`` (not audited).

cuOpt / tri-modal does not recompute miles here; we attach solver status and explain how
NVIDIA/cuOpt share guidance aligns with shorter average last-mile when mock-parcel improves.
"""

from __future__ import annotations

from typing import Any

from unie_cortex.config import settings
from unie_cortex.network.transport_geo import CO2E_KG_PER_PACKAGE_MILE_ILLUSTRATIVE, geodesic_miles_zip5


def _postal_by_warehouse_id(warehouses: list[dict[str, Any]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for w in warehouses:
        if not isinstance(w, dict):
            continue
        wid = str(w.get("id") or "").strip()
        if not wid:
            continue
        z = str(w.get("postal") or "").strip()
        if z:
            out[wid] = z
    return out


def _best_single_hub_id(fnc: dict[str, Any] | None, sku: str) -> str | None:
    if not isinstance(fnc, dict):
        return None
    for row in fnc.get("per_sku") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("sku") or "").strip() != str(sku).strip():
            continue
        b = row.get("best_single_hub_by_fully_loaded")
        if isinstance(b, dict) and b.get("warehouse_id"):
            return str(b.get("warehouse_id")).strip()
    return None


def _linehaul_miles_monthly_for_sku(
    allocation: dict[str, Any] | None,
    sku: str,
    postal_by_id: dict[str, str],
) -> tuple[float, list[dict[str, Any]]]:
    """Sum geodesic hub→spoke miles × monthly flow units for this SKU."""
    if not isinstance(allocation, dict):
        return 0.0, []
    total = 0.0
    detail: list[dict[str, Any]] = []
    for line in allocation.get("lines") or []:
        if not isinstance(line, dict):
            continue
        if str(line.get("sku") or "").strip() != str(sku).strip():
            continue
        for leg in line.get("transfer_from_hub") or []:
            if not isinstance(leg, dict):
                continue
            fid = str(leg.get("from_warehouse_id") or "").strip()
            tid = str(leg.get("to_warehouse_id") or "").strip()
            try:
                u = float(leg.get("monthly_flow_units") or leg.get("units") or 0.0)
            except (TypeError, ValueError):
                u = 0.0
            if u <= 0 or not fid or not tid:
                continue
            po = postal_by_id.get(fid)
            pt = postal_by_id.get(tid)
            if not po or not pt:
                continue
            mi = geodesic_miles_zip5(po, pt)
            if mi is None:
                continue
            leg_mi = mi * u
            total += leg_mi
            detail.append(
                {
                    "from_warehouse_id": fid,
                    "to_warehouse_id": tid,
                    "monthly_flow_units": round(u, 4),
                    "geodesic_miles": round(mi, 4),
                    "geodesic_miles_times_units_monthly": round(leg_mi, 4),
                }
            )
    return round(total, 4), detail


def _expected_last_mile_miles_per_shipment(
    state_coverage: list[dict[str, Any]],
    primary_wh: str,
    postal_by_id: dict[str, str],
) -> float | None:
    wh_postal = postal_by_id.get(primary_wh)
    if not wh_postal:
        return None
    acc = 0.0
    wsum = 0.0
    for row in state_coverage:
        if not isinstance(row, dict):
            continue
        dest = str(row.get("destination_postal") or "").strip()
        try:
            share = float(row.get("demand_share") or 0.0)
        except (TypeError, ValueError):
            share = 0.0
        if share <= 0 or not dest:
            continue
        mi = geodesic_miles_zip5(wh_postal, dest)
        if mi is None:
            continue
        acc += share * mi
        wsum += share
    if wsum < 0.99:
        return None
    return round(acc, 6)


def _cuopt_context_block(
    tri: dict[str, Any] | None,
    cuopt_intel: dict[str, Any] | None,
) -> dict[str, Any]:
    tri_st = str(tri.get("status") or "") if isinstance(tri, dict) else ""
    nv = tri.get("nvidia_enhanced") if isinstance(tri, dict) else None
    nv_st = str(nv.get("status") or "") if isinstance(nv, dict) else ""
    ci_st = str(cuopt_intel.get("status") or "") if isinstance(cuopt_intel, dict) else ""
    return {
        "schema_version": "cuopt_green_alignment_context_v1",
        "multi_dc_placement_tri_modal_status": tri_st or None,
        "nvidia_enhanced_status": nv_st or None,
        "cuopt_allocation_intelligence_status": ci_st or None,
        "note": (
            "NVIDIA cuOpt tri-modal optimizes fused operating-cost inputs for the warehouse matrix; when "
            "``cuopt_allocation_intelligence`` applies share nudges, the intent is to move stocking toward "
            "economically efficient nodes — which typically correlates with lower national expected mock parcel "
            "(a proxy for shorter average last-mile in this grid). This block does not run a second mileage "
            "solver; mileage deltas above come from placement_mock_rate_grids routing vs single-hub counterfactuals."
        ),
    }


def build_green_logistics_impact_v1(
    *,
    placement_mock_rate_grids: dict[str, Any] | None,
    allocation: dict[str, Any] | None,
    fulfillment_network_comparison: dict[str, Any] | None,
    warehouses: list[dict[str, Any]],
    demand_by_sku: dict[str, Any],
    hub_warehouse_id: str | None,
    multi_dc_placement_tri_modal: dict[str, Any] | None = None,
    cuopt_allocation_intelligence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Per-SKU expected last-mile miles (48-state demand-weighted) for multi-routed vs best single hub,
    plus illustrative monthly CO₂e delta and optional inter-DC linehaul mile×units.
    """
    if not isinstance(placement_mock_rate_grids, dict):
        return {"status": "skipped", "message": "placement_mock_rate_grids missing", "per_sku": []}
    if str(placement_mock_rate_grids.get("status") or "") != "complete":
        return {
            "status": "skipped",
            "message": f"placement grid not complete ({placement_mock_rate_grids.get('status')})",
            "per_sku": [],
        }

    coverage = placement_mock_rate_grids.get("state_shipping_coverage")
    if not isinstance(coverage, list) or not coverage:
        return {"status": "skipped", "message": "state_shipping_coverage empty", "per_sku": []}

    postal_by_id = _postal_by_warehouse_id(warehouses)
    detour = float(getattr(settings, "direct_parcel_network_detour_multiplier", 1.0) or 1.0)
    if detour < 1.0:
        detour = 1.0

    lh_kg = float(getattr(settings, "green_linehaul_kg_co2e_per_mile", 0.00015) or 0.00015)
    lm_kg = float(
        getattr(settings, "green_last_mile_kg_co2e_per_package_mile", CO2E_KG_PER_PACKAGE_MILE_ILLUSTRATIVE)
        or CO2E_KG_PER_PACKAGE_MILE_ILLUSTRATIVE
    )

    hub_cfg = str(hub_warehouse_id or "").strip() or None

    per_sku_out: list[dict[str, Any]] = []

    for sku, dem in demand_by_sku.items():
        if not isinstance(dem, dict):
            continue
        sku_s = str(sku).strip()
        if not sku_s:
            continue
        try:
            monthly = float(dem.get("monthly_units_est_mid") or 0.0)
        except (TypeError, ValueError):
            monthly = 0.0
        if monthly <= 0:
            continue

        multi_per_ship = 0.0
        wsum = 0.0
        for row in coverage:
            if not isinstance(row, dict):
                continue
            prim = str(row.get("primary_warehouse_id") or "").strip()
            dest = str(row.get("destination_postal") or "").strip()
            try:
                share = float(row.get("demand_share") or 0.0)
            except (TypeError, ValueError):
                share = 0.0
            if share <= 0 or not prim or not dest:
                continue
            op = postal_by_id.get(prim)
            if not op:
                continue
            mi = geodesic_miles_zip5(op, dest)
            if mi is None:
                continue
            multi_per_ship += share * mi
            wsum += share
        if wsum < 0.99:
            continue
        multi_per_ship = round(multi_per_ship, 6)

        best_wh = _best_single_hub_id(fulfillment_network_comparison, sku_s)
        single_best_per_ship = (
            _expected_last_mile_miles_per_shipment(coverage, best_wh, postal_by_id) if best_wh else None
        )

        single_cfg_per_ship = (
            _expected_last_mile_miles_per_shipment(coverage, hub_cfg, postal_by_id)
            if hub_cfg and hub_cfg in postal_by_id
            else None
        )

        delta_vs_best = None
        if single_best_per_ship is not None:
            delta_vs_best = round(single_best_per_ship - multi_per_ship, 6)

        monthly_multi = round(multi_per_ship * monthly, 4)
        monthly_single_best = (
            round(single_best_per_ship * monthly, 4) if single_best_per_ship is not None else None
        )
        monthly_saved_vs_best = (
            round(delta_vs_best * monthly, 4) if delta_vs_best is not None else None
        )

        multi_det = round(multi_per_ship * detour, 6)
        single_best_det = round(single_best_per_ship * detour, 6) if single_best_per_ship is not None else None
        delta_det = round(single_best_det - multi_det, 6) if single_best_det is not None else None

        co2e_delta_month = (
            round(monthly * delta_vs_best * lm_kg, 6) if delta_vs_best is not None else None
        )
        co2e_delta_month_detour = (
            round(monthly * delta_det * lm_kg, 6) if delta_det is not None else None
        )

        lh_miles, lh_detail = _linehaul_miles_monthly_for_sku(allocation, sku_s, postal_by_id)
        co2e_linehaul_month = round(lh_miles * lh_kg, 6) if lh_miles > 0 else 0.0

        per_sku_out.append(
            {
                "sku": sku_s,
                "monthly_demand_units": round(monthly, 4),
                "last_mile_geodesic": {
                    "distance_model": "geodesic_zip_centroid_v1",
                    "demand_weight_source": "placement_mock_rate_grids.state_shipping_coverage.demand_share",
                    "expected_miles_per_outbound_shipment_multi_routed": multi_per_ship,
                    "expected_miles_per_outbound_shipment_single_best_hub": single_best_per_ship,
                    "best_single_hub_warehouse_id": best_wh,
                    "expected_miles_per_outbound_shipment_single_configured_hub": single_cfg_per_ship,
                    "configured_hub_warehouse_id": hub_cfg,
                    "delta_miles_saved_per_shipment_vs_best_single_hub": delta_vs_best,
                    "monthly_package_miles_multi_routed": monthly_multi,
                    "monthly_package_miles_single_best_hub": monthly_single_best,
                    "monthly_miles_saved_vs_best_single_hub": monthly_saved_vs_best,
                    "direct_parcel_network_detour_multiplier": detour,
                    "expected_miles_per_shipment_multi_routed_detour_adjusted": multi_det,
                    "expected_miles_per_shipment_single_best_detour_adjusted": single_best_det,
                    "delta_miles_saved_per_shipment_vs_best_single_detour_adjusted": delta_det,
                },
                "illustrative_co2e_last_mile": {
                    "note": "Illustrative kg CO₂e / month from last-mile mile delta × monthly units; not audited.",
                    "kg_co2e_per_package_mile": lm_kg,
                    "monthly_kg_delta_vs_best_single_hub": co2e_delta_month,
                    "monthly_kg_delta_vs_best_single_hub_detour_adjusted": co2e_delta_month_detour,
                },
                "inter_network_linehaul": {
                    "note": (
                        "Geodesic miles × monthly hub→spoke flow units (allocation). Separate from last-mile; "
                        "uses linehaul illustrative kg/mile."
                    ),
                    "kg_co2e_per_mile": lh_kg,
                    "monthly_geodesic_miles_times_units": lh_miles,
                    "illustrative_monthly_kg_co2e": co2e_linehaul_month,
                    "legs": lh_detail[:24],
                },
            }
        )

    out: dict[str, Any] = {
        "status": "complete" if per_sku_out else "skipped",
        "schema_version": "green_logistics_impact_v1",
        "human_note": (
            "Last-mile expectations weight each state's hub ZIP by the same demand_share used for mock-parcel "
            "routing (48 contiguous states). Multi-routed uses primary_warehouse_id per state; single-hub uses "
            "fulfillment_network_comparison.best_single_hub_by_fully_loaded for the counterfactual. "
            "CO₂e uses configurable illustrative constants (see settings.green_*)."
        ),
        "kg_co2e_per_package_mile_last_mile_default": lm_kg,
        "kg_co2e_per_mile_linehaul_proxy_default": lh_kg,
        "cuopt_and_solver_context": _cuopt_context_block(
            multi_dc_placement_tri_modal,
            cuopt_allocation_intelligence,
        ),
        "per_sku": per_sku_out,
    }
    if not per_sku_out:
        out["message"] = "no sku with positive monthly_units_est_mid or mileage incomplete"
    return out


def append_green_bullets_to_synthesis(
    synthesis: dict[str, Any],
    green_logistics_impact: dict[str, Any] | None,
) -> None:
    """Append 0–N narrative bullets to item_intelligence_synthesis.run_summary_bullets (mutates in place)."""
    if not isinstance(synthesis, dict) or not isinstance(green_logistics_impact, dict):
        return
    if str(green_logistics_impact.get("status") or "") != "complete":
        return
    bullets = synthesis.get("run_summary_bullets")
    if not isinstance(bullets, list):
        return
    for row in green_logistics_impact.get("per_sku") or []:
        if not isinstance(row, dict):
            continue
        sku = str(row.get("sku") or "").strip()
        if not sku:
            continue
        lm = row.get("last_mile_geodesic") if isinstance(row.get("last_mile_geodesic"), dict) else {}
        d = lm.get("delta_miles_saved_per_shipment_vs_best_single_hub")
        co2b = row.get("illustrative_co2e_last_mile") if isinstance(row.get("illustrative_co2e_last_mile"), dict) else {}
        kg = co2b.get("monthly_kg_delta_vs_best_single_hub")
        try:
            dv = float(d) if d is not None else None
        except (TypeError, ValueError):
            dv = None
        try:
            kgv = float(kg) if kg is not None else None
        except (TypeError, ValueError):
            kgv = None
        if dv is not None and dv > 1e-6:
            kgs = f"~{kgv:.4f} kg CO₂e/mo" if kgv is not None else "illustrative CO₂e/mo"
            bullets.append(
                f"{sku}: multi-routed last-mile (grid) saves ~{dv:.1f} mi per shipment vs best single hub "
                f"({kgs} at configured illustrative factors — see green_logistics_impact)."
            )
        elif dv is not None and dv < -1e-6:
            bullets.append(
                f"{sku}: in this 48-state proxy, best single hub is ~{abs(dv):.1f} mi/shipment shorter than "
                "current routing — validate shares or grid assignment (green_logistics_impact)."
            )
    cu = green_logistics_impact.get("cuopt_and_solver_context")
    if isinstance(cu, dict) and str(cu.get("nvidia_enhanced_status") or "") == "complete":
        bullets.append(
            "NVIDIA cuOpt tri-modal completed for this run — share guidance is designed to align economics with "
            "network efficiency; cross-check green_logistics_impact for last-mile mile/illustrative emissions context."
        )

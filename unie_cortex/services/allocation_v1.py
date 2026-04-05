"""
Deterministic multi-node stock placement from monthly demand and lane cost.

Inputs mirror cuOpt-style nodes/lanes but operate at SKU-unit granularity.
Uses proportional split by warehouse target_share_pct (normalized to sum to 1),
then transfer from primary (hub). Per-warehouse ``recommended_monthly_units`` are
**integers**: proportional shares are floored, then any remainder whole units
are assigned to warehouses with the **largest fractional parts** (ties: earlier
in the warehouse list wins).
"""

from __future__ import annotations

import math
from typing import Any

from unie_cortex.config import settings
from unie_cortex.network.ftl_mock import choose_linehaul_mode
from unie_cortex.network.seller_mixed_pallet_linehaul import build_seller_consolidated_linehaul_leg

# Catalog SKUs often lack dimensions → cube_cuft=0. Without imputation, seller mixed-pallet LTL/FTL never runs.
_NOMINAL_LB_PER_CUFT_FOR_LINEHAUL_IMPUTE = 10.0


def _hub_spoke_leg_transfer_usd(
    *,
    seller_mixed_pallet_linehaul: bool,
    units: int,
    weight_lb_per_unit: float,
    cube_cuft_per_unit: float,
    cost_per_lb_lane: float,
    consolidated_linehaul_cost_multiplier: float,
    freight_mode: str,
    ftl_threshold_total_lb: float,
) -> tuple[float, dict[str, Any]]:
    """
    Monthly USD for one hub→node leg. Seller mode matches order-planning consolidated linehaul mock
    (pallet slot fraction × one reference-slot LTL/FTL baseline); else legacy lane $/lb × weight × units.
    """
    u = max(0, int(units))
    if u <= 0:
        return 0.0, {"method": "no_flow"}

    w_lb = max(0.0, float(weight_lb_per_unit))
    leg_w = float(u) * w_lb
    linear = round(float(u) * w_lb * float(cost_per_lb_lane), 4)
    cu = max(0.0, float(cube_cuft_per_unit))
    leg_cuft = float(u) * cu
    cube_imputed_from_leg_weight = False

    if not seller_mixed_pallet_linehaul:
        return linear, {"method": "lane_dollar_per_lb_v1", "est_cost_usd_linear_lane_fallback": linear}

    if leg_cuft <= 1e-9 and leg_w > 1e-9:
        leg_cuft = max(leg_cuft, leg_w / _NOMINAL_LB_PER_CUFT_FOR_LINEHAUL_IMPUTE)
        cube_imputed_from_leg_weight = True

    if leg_cuft <= 1e-9:
        return linear, {
            "method": "lane_dollar_per_lb_v1",
            "reason": "missing_or_zero_unit_cube_cuft_and_weight",
            "est_cost_usd_linear_lane_fallback": linear,
        }

    mode = choose_linehaul_mode(
        leg_w,
        freight_mode=freight_mode,
        ftl_threshold_total_lb=ftl_threshold_total_lb,
    )
    fr = build_seller_consolidated_linehaul_leg(
        mode="ftl" if mode == "ftl" else "ltl",
        qty=max(1, u),
        total_w=leg_w,
        total_cuft=leg_cuft,
        consolidated_linehaul_cost_multiplier=consolidated_linehaul_cost_multiplier,
    )
    usd = float(fr.get("total_usd") or 0.0)
    meta = {
        "method": "seller_mixed_pallet_linehaul_v1",
        "linehaul_mode": fr.get("mode"),
        "pallet_slot_fraction": fr.get("pallet_slot_fraction"),
        "baseline_full_reference_pallet_usd": fr.get("baseline_full_reference_pallet_usd"),
        "est_cost_usd_linear_lane_counterfactual": linear,
    }
    if cube_imputed_from_leg_weight:
        meta["cube_imputed_from_monthly_leg_weight_lb"] = True
        meta["cube_imputation_lb_per_cuft_assumed"] = _NOMINAL_LB_PER_CUFT_FOR_LINEHAUL_IMPUTE
        meta["note"] = (
            "Monthly hub→spoke cube was 0 (missing item dimensions in catalog). "
            f"Imputed leg cube as leg_weight_lb / {_NOMINAL_LB_PER_CUFT_FOR_LINEHAUL_IMPUTE} so LTL/FTL mock runs; "
            "add length_in × width_in × height_in for SKU-accurate pallet fraction."
        )
    return round(usd, 4), meta


def _integer_split_proportional(total_demand: float, norm_shares: list[float]) -> list[int]:
    """
    Split rounded monthly demand into whole units across normalized shares.

    Largest-remainder (Hamilton) method so counts sum to ``int(round(total_demand))``.
    """
    total_int = max(0, int(round(float(total_demand))))
    n = len(norm_shares)
    if n == 0:
        return []
    if total_int == 0:
        return [0] * n
    raw = [total_int * float(ns) for ns in norm_shares]
    floors = [int(math.floor(r + 1e-9)) for r in raw]
    leftover = total_int - sum(floors)
    fracs = [(raw[i] - floors[i], i) for i in range(n)]
    fracs.sort(key=lambda t: (-t[0], t[1]))
    out = list(floors)
    for k in range(max(0, leftover)):
        out[fracs[k][1]] += 1
    return out


def replenishment_months_for_min_transfer_batch(
    monthly_flow_units: float,
    min_units: float,
    *,
    max_months: int = 12,
) -> dict[str, Any]:
    """
    Replenishment cadence (months of destination flow) so one inter-warehouse move
    reaches ``min_units``. Prefers 2 months when ``2 * flow >= min_units``.
    """
    mf = float(monthly_flow_units)
    mn = float(min_units)
    if mf <= 0 or mn <= 0:
        return {
            "recommended_replenishment_months": None,
            "recommended_transfer_batch_units": None,
            "meets_minimum_at_monthly_cadence": True,
            "feasible_within_max_months": True,
            "note": None,
        }
    if mf >= mn:
        return {
            "recommended_replenishment_months": 1,
            "recommended_transfer_batch_units": round(mf, 3),
            "meets_minimum_at_monthly_cadence": True,
            "feasible_within_max_months": True,
            "note": None,
        }
    if 2 * mf >= mn:
        m = 2
    else:
        m = None
        for cand in range(3, max_months + 1):
            if cand * mf >= mn:
                m = cand
                break
        if m is None:
            return {
                "recommended_replenishment_months": None,
                "recommended_transfer_batch_units": None,
                "meets_minimum_at_monthly_cadence": False,
                "feasible_within_max_months": False,
                "note": (
                    f"Even a {max_months}-month replenishment batch (~{max_months * mf:.1f} units) "
                    f"stays below the minimum move of {mn:.0f} units — combine SKUs on the lane, "
                    "negotiate a lower MOQ, consolidate nodes, or raise velocity before recurring transfers."
                ),
            }
    return {
        "recommended_replenishment_months": m,
        "recommended_transfer_batch_units": round(m * mf, 3),
        "meets_minimum_at_monthly_cadence": False,
        "feasible_within_max_months": True,
        "note": None,
    }


def allocate_skus(
    skus: list[dict[str, Any]],
    warehouses: list[dict[str, Any]],
    lanes: list[dict[str, Any]],
    *,
    hub_id: str | None = None,
    min_inter_warehouse_transfer_units: float | None = None,
    max_months_to_meet_min_transfer: int = 12,
    seller_mixed_pallet_linehaul: bool = False,
    consolidated_linehaul_cost_multiplier: float = 1.0,
    freight_mode: str = "auto",
    ftl_threshold_total_lb: float = 12_000.0,
) -> dict[str, Any]:
    """
    skus: [{sku, monthly_units, weight_lb, cube_cuft}]
    warehouses: [{id, target_share_pct?}]  shares default to equal if missing
    lanes: [{from_id, to_id, cost_per_lb}]  used for hub -> node transfer estimate
    hub_id: origin of transfers; defaults to first warehouse id
    min_inter_warehouse_transfer_units: when set, each hub→node leg gets batch guidance;
        prefers 2-month replenishment when that reaches the minimum, else smallest m≤max_months.
    max_months_to_meet_min_transfer: cap when searching for a batch size that clears the minimum.
    seller_mixed_pallet_linehaul: when True, hub→spoke leg USD uses the same mock as seller order-planning
        (``build_seller_consolidated_linehaul_leg``); SKUs without unit ``cube_cuft`` fall back to lane $/lb.
    consolidated_linehaul_cost_multiplier: passed through to the seller linehaul mock (same as scenarios).
    freight_mode / ftl_threshold_total_lb: linehaul mode selection on actual leg weight (same as scenarios).
    """
    if not skus or not warehouses:
        return {
            "status": "skipped",
            "message": "skus and warehouses required",
            "lines": [],
            "total_transfer_cost_est_usd": 0.0,
        }

    ids = [w["id"] for w in warehouses]
    primary = hub_id or ids[0]
    if primary not in ids:
        primary = ids[0]

    shares = []
    for w in warehouses:
        p = w.get("target_share_pct")
        shares.append(float(p) if p is not None else None)
    if any(x is not None for x in shares) and not all(x is not None for x in shares):
        # partial specification — fill missing with equal residue
        known = [x for x in shares if x is not None]
        residue = max(0.0, 100.0 - sum(known))
        n_missing = sum(1 for x in shares if x is None)
        fill = residue / n_missing if n_missing else 0.0
        shares = [x if x is not None else fill for x in shares]
    elif all(x is None for x in shares):
        eq = 100.0 / len(ids)
        shares = [eq] * len(ids)
    else:
        shares = [float(x) for x in shares]  # type: ignore[arg-type]

    total_share = sum(shares)
    if total_share <= 0:
        shares = [100.0 / len(ids)] * len(ids)
        total_share = 100.0
    norm_shares = [s / total_share for s in shares]

    lane_cost: dict[tuple[str, str], float] = {}
    for L in lanes:
        fid, tid = L.get("from_id"), L.get("to_id")
        if fid and tid:
            lane_cost[(str(fid), str(tid))] = float(L.get("cost_per_lb") or 0.0)

    lines: list[dict[str, Any]] = []
    total_transfer = 0.0

    for s in skus:
        sku = s.get("sku")
        d = float(s.get("monthly_units") or 0.0)
        w_lb = float(s.get("weight_lb") or 0.0)
        cube_u = float(s.get("cube_cuft") or 0.0)
        if d <= 0:
            continue
        int_units = _integer_split_proportional(d, norm_shares)
        placement = []
        for i, wid in enumerate(ids):
            units = int_units[i]
            placement.append({"warehouse_id": wid, "recommended_monthly_units": units})

        xfer_cost = 0.0
        xfer_detail = []
        months_for_line: list[int] = []
        infeasible_min_transfer = False
        for i, wid in enumerate(ids):
            if wid == primary:
                continue
            units = placement[i]["recommended_monthly_units"]
            if units <= 0:
                continue
            cplb = lane_cost.get((primary, wid), 0.0)
            leg, leg_meta = _hub_spoke_leg_transfer_usd(
                seller_mixed_pallet_linehaul=seller_mixed_pallet_linehaul,
                units=units,
                weight_lb_per_unit=w_lb,
                cube_cuft_per_unit=cube_u,
                cost_per_lb_lane=cplb,
                consolidated_linehaul_cost_multiplier=consolidated_linehaul_cost_multiplier,
                freight_mode=freight_mode,
                ftl_threshold_total_lb=ftl_threshold_total_lb,
            )
            xfer_cost += leg
            leg_row: dict[str, Any] = {
                "from_warehouse_id": primary,
                "to_warehouse_id": wid,
                "units": units,
                "monthly_flow_units": units,
                "est_cost_usd": leg,
                "cost_per_lb_lane": cplb,
                "transfer_pricing": leg_meta,
            }
            if min_inter_warehouse_transfer_units is not None and min_inter_warehouse_transfer_units > 0:
                batch_info = replenishment_months_for_min_transfer_batch(
                    units,
                    float(min_inter_warehouse_transfer_units),
                    max_months=max(1, int(max_months_to_meet_min_transfer)),
                )
                leg_row["min_transfer_batch"] = batch_info
                rm = batch_info.get("recommended_replenishment_months")
                if rm is not None:
                    months_for_line.append(int(rm))
                if not batch_info.get("feasible_within_max_months"):
                    infeasible_min_transfer = True
                b_units = float(batch_info.get("recommended_transfer_batch_units") or 0.0)
                if b_units > 0:
                    bu = max(1, int(round(b_units)))
                    batch_usd, _ = _hub_spoke_leg_transfer_usd(
                        seller_mixed_pallet_linehaul=seller_mixed_pallet_linehaul,
                        units=bu,
                        weight_lb_per_unit=w_lb,
                        cube_cuft_per_unit=cube_u,
                        cost_per_lb_lane=cplb,
                        consolidated_linehaul_cost_multiplier=consolidated_linehaul_cost_multiplier,
                        freight_mode=freight_mode,
                        ftl_threshold_total_lb=ftl_threshold_total_lb,
                    )
                    leg_row["est_cost_usd_at_recommended_batch"] = batch_usd
            xfer_detail.append(leg_row)

        total_transfer += xfer_cost
        network_adj: dict[str, Any] | None = None
        if min_inter_warehouse_transfer_units:
            if infeasible_min_transfer:
                network_adj = {
                    "adjusted_target_days_cover": None,
                    "min_inter_warehouse_transfer_units": float(min_inter_warehouse_transfer_units),
                    "max_replenishment_months_applied": None,
                    "rationale": (
                        "At least one hub→node lane cannot reach the minimum move size within "
                        f"{max(1, int(max_months_to_meet_min_transfer))} month(s) of flow — "
                        "see per-leg min_transfer_batch.note; combine freight or renegotiate MOQ."
                    ),
                    "infeasible_at_configured_horizon": True,
                }
            elif months_for_line:
                max_m = max(months_for_line)
                if max_m > 1:
                    daily = d / 30.0
                    baseline_days = float(getattr(settings, "planning_default_target_days_cover", 75.0) or 75.0)
                    max_adj_days = float(
                        getattr(settings, "network_placement_adjustment_max_days_cover", 90.0) or 90.0
                    )
                    raw_adj_days = 30.0 * max_m
                    adj_days = min(raw_adj_days, max_adj_days)
                    capped = adj_days + 1e-6 < raw_adj_days
                    adj_cover = int(math.ceil(daily * adj_days)) if daily > 0 else None
                    base_cover = int(math.ceil(daily * baseline_days)) if daily > 0 else None
                    base_cover_30 = int(math.ceil(daily * 30.0)) if daily > 0 else None
                    rationale = (
                        f"At least one hub→node lane moves fewer than "
                        f"{float(min_inter_warehouse_transfer_units):.0f} units/month; "
                        f"replenishment batch sizing implies ~{max_m} month(s) of destination flow."
                    )
                    if capped:
                        rationale += (
                            f" Stated cover is capped at {max_adj_days:.0f} days (planning norm); "
                            f"unadjusted would be ~{raw_adj_days:.0f} days — raise velocity, consolidate nodes, "
                            "or lower MOQ to stay near 60–90d stocking."
                        )
                    else:
                        rationale += " Extended cover aligns batch MOQ with typical 60–90d planning targets."
                    network_adj = {
                        "adjusted_target_days_cover": adj_days,
                        "baseline_target_days_cover": baseline_days,
                        "adjusted_suggested_total_units_for_target_cover": adj_cover,
                        "baseline_suggested_total_units_for_target_cover": base_cover,
                        "baseline_suggested_total_units_for_target_cover_30d": base_cover_30,
                        "max_replenishment_months_applied": max_m,
                        "min_inter_warehouse_transfer_units": float(min_inter_warehouse_transfer_units),
                        "rationale": rationale,
                    }
                    if capped:
                        network_adj["raw_extended_target_days_cover_uncapped"] = raw_adj_days

        line_out: dict[str, Any] = {
            "sku": sku,
            "monthly_demand_units": d,
            "placement": placement,
            "transfer_from_hub": xfer_detail,
            "transfer_cost_est_usd": round(xfer_cost, 4),
        }
        if network_adj is not None:
            line_out["network_placement_adjustment"] = network_adj
        lines.append(line_out)

    out: dict[str, Any] = {
        "status": "complete",
        "hub_warehouse_id": primary,
        "warehouse_share_normalized": dict(zip(ids, norm_shares)),
        "placement_units_method": "integer_largest_remainder",
        "lines": lines,
        "total_transfer_cost_est_usd": round(total_transfer, 4),
        "seller_mixed_pallet_linehaul_applied": bool(seller_mixed_pallet_linehaul),
        "transfer_linehaul_model": (
            "seller_mixed_pallet_linehaul_v1"
            if seller_mixed_pallet_linehaul
            else "lane_dollar_per_lb_v1"
        ),
        "note": (
            "V1 proportional allocator; hub→spoke transfer uses seller mixed-pallet linehaul mock when enabled "
            "(aligns with order-planning consolidated leg); else lane $/lb × weight × flow. "
            "CUOPT_NIM_URL path for VRP-grade optimization."
        ),
    }
    if min_inter_warehouse_transfer_units is not None:
        out["min_inter_warehouse_transfer_units"] = float(min_inter_warehouse_transfer_units)
        out["max_months_to_meet_min_transfer"] = int(max(1, max_months_to_meet_min_transfer))
    return out

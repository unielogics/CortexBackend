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
) -> dict[str, Any]:
    """
    skus: [{sku, monthly_units, weight_lb, cube_cuft}]
    warehouses: [{id, target_share_pct?}]  shares default to equal if missing
    lanes: [{from_id, to_id, cost_per_lb}]  used for hub -> node transfer estimate
    hub_id: origin of transfers; defaults to first warehouse id
    min_inter_warehouse_transfer_units: when set, each hub→node leg gets batch guidance;
        prefers 2-month replenishment when that reaches the minimum, else smallest m≤max_months.
    max_months_to_meet_min_transfer: cap when searching for a batch size that clears the minimum.
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
            leg = round(units * w_lb * cplb, 4)
            xfer_cost += leg
            leg_row: dict[str, Any] = {
                "from_warehouse_id": primary,
                "to_warehouse_id": wid,
                "units": units,
                "monthly_flow_units": units,
                "est_cost_usd": leg,
                "cost_per_lb_lane": cplb,
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
                    leg_row["est_cost_usd_at_recommended_batch"] = round(b_units * w_lb * cplb, 4)
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
                    adj_days = 30.0 * max_m
                    adj_cover = int(math.ceil(daily * adj_days)) if daily > 0 else None
                    base_cover = int(math.ceil(daily * 30.0)) if daily > 0 else None
                    network_adj = {
                        "adjusted_target_days_cover": adj_days,
                        "baseline_target_days_cover": 30.0,
                        "adjusted_suggested_total_units_for_target_cover": adj_cover,
                        "baseline_suggested_total_units_for_target_cover_30d": base_cover,
                        "max_replenishment_months_applied": max_m,
                        "min_inter_warehouse_transfer_units": float(min_inter_warehouse_transfer_units),
                        "rationale": (
                            f"At least one hub→node lane moves fewer than "
                            f"{float(min_inter_warehouse_transfer_units):.0f} units/month; "
                            f"planning cover was extended to {max_m} month(s) of flow so a replenishment "
                            "batch can meet the minimum move size."
                        ),
                    }

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
        "note": "V1 proportional allocator; use CUOPT_NIM_URL path for VRP-grade optimization.",
    }
    if min_inter_warehouse_transfer_units is not None:
        out["min_inter_warehouse_transfer_units"] = float(min_inter_warehouse_transfer_units)
        out["max_months_to_meet_min_transfer"] = int(max(1, max_months_to_meet_min_transfer))
    return out

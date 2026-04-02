"""
Greedy US warehouse network expansion: volume gates, MOQ per node, saturation before
adding further nodes, hot-ZIP3 signal from label history, and mock last-mile cost.

Does not replace CUOPT; produces a repeatable recommendation for item intelligence.
"""

from __future__ import annotations

import math
import re
from typing import Any

from unie_cortex.network.demand_rollup import rollup_label_demand
from unie_cortex.config import settings
from unie_cortex.network.us_state_demand_share import (
    build_blended_state_demand_weights_from_labels,
    demand_share_metadata,
)
from unie_cortex.network.parcel_mock import best_mock_parcel_among_carriers
from unie_cortex.network.zones import CarrierCode
from unie_cortex.services.warehouse_mock_rate_grid import (
    CONTIGUOUS_STATE_HUB_DESTINATIONS_48,
    build_warehouse_mock_placement_grids,
    merge_warehouse_target_shares_for_placement,
)
from unie_cortex.network.facility_freight_mock_defaults import (
    enrich_warehouse_node_dict,
    enrich_warehouse_node_with_regional_fallback,
)
from unie_cortex.network.prep_center_loader import prep_center_candidate_warehouses_raw


def default_us_candidate_warehouses() -> list[dict[str, Any]]:
    """
    Prefer Prep Center export bundle (``prep_center_candidate_warehouses.json``) when present;
    otherwise six regional archetypes (contiguous US coverage intent).
    """
    raw = prep_center_candidate_warehouses_raw()
    if raw:
        out: list[dict[str, Any]] = []
        for w in raw:
            if not isinstance(w, dict):
                continue
            node = enrich_warehouse_node_dict(dict(w))
            node = enrich_warehouse_node_with_regional_fallback(node)
            out.append(node)
        if out:
            return out
    base = [
        {"id": "reg_ne", "postal": "07102"},
        {"id": "reg_se", "postal": "30303"},
        {"id": "reg_mw", "postal": "60607"},
        {"id": "reg_tx", "postal": "77002"},
        {"id": "reg_mt", "postal": "80202"},
        {"id": "reg_wc", "postal": "90012"},
    ]
    return [enrich_warehouse_node_dict(dict(w)) for w in base]


def _zip3_to_sample_zip5(z3: str) -> str:
    z = re.sub(r"\D", "", str(z3))[:3].zfill(3)
    return z + "01" if len(z) == 3 else "10001"


def _inverse_parcel_shares(mean_by_wh: dict[str, float], ids: list[str]) -> dict[str, float]:
    inv = {wid: 1.0 / max(0.25, float(mean_by_wh.get(wid) or 99.0)) for wid in ids}
    s = sum(inv.values()) or 1.0
    return {wid: inv[wid] / s for wid in ids}


def _flows(demand: float, shares: dict[str, float], ids: list[str]) -> list[float]:
    return [demand * float(shares.get(wid, 0.0)) for wid in ids]


def _max_nodes_for_monthly_volume(monthly_total: float, tier_bounds: list[tuple[float, int]]) -> int:
    """tier_bounds: sorted (min_demand_exclusive, max_nodes) — first match where monthly_total < bound wins previous."""
    k = 1
    for threshold, max_k in sorted(tier_bounds, key=lambda x: x[0]):
        if monthly_total >= threshold:
            k = max(k, max_k)
    return min(k, 6)


def _hot_zone_last_mile_proxy(
    origin_postal: str,
    hot_zip3: list[str],
    *,
    weight_lb: float,
    carriers: list[CarrierCode],
) -> float:
    if not hot_zip3:
        return 0.0
    total = 0.0
    n = 0
    for z3 in hot_zip3[:20]:
        dest = _zip3_to_sample_zip5(z3)
        best, _ = best_mock_parcel_among_carriers(
            carriers,
            origin_postal=origin_postal,
            dest_postal=dest,
            weight_lb=weight_lb,
            length_in=12.0,
            width_in=10.0,
            height_in=8.0,
        )
        total += float(best.get("total_usd") or 0.0)
        n += 1
    return total / n if n else 0.0




def _demand_weighted_mock_parcel_usd_from_origin(
    origin_postal: str,
    weight_lb: float,
    carriers: list[CarrierCode],
    state_shares: dict[str, float],
) -> float:
    """Expected mock parcel $ to random US order: sum_s share_s * best_mock(origin, state_hub_s)."""
    oz = (origin_postal or "10001").strip()
    total = 0.0
    for m in CONTIGUOUS_STATE_HUB_DESTINATIONS_48:
        st = str(m["state"])
        w = float(state_shares.get(st) or 0.0)
        if w <= 0:
            continue
        best, _ = best_mock_parcel_among_carriers(
            carriers,
            origin_postal=oz,
            dest_postal=str(m["postal"]),
            weight_lb=weight_lb,
            length_in=12.0,
            width_in=10.0,
            height_in=8.0,
        )
        total += w * float(best.get("total_usd") or 0.0)
    return total

def _gates_allow_k_nodes(
    demand: float,
    ids: list[str],
    shares: dict[str, float],
    *,
    min_units_per_node: float,
    min_units_per_node_when_three_or_more_nodes: float,
) -> bool:
    flows = _flows(demand, shares, ids)
    floor = min_units_per_node_when_three_or_more_nodes if len(ids) >= 3 else min_units_per_node
    if any(f + 1e-6 < floor for f in flows):
        return False
    return True


def recommend_warehouse_network(
    *,
    monthly_total_demand_units: float,
    seed_warehouses: list[dict[str, Any]],
    hub_warehouse_id: str | None,
    labels: list[dict[str, Any]],
    catalog_skus: set[str],
    weight_lb: float,
    min_monthly_units_to_expand_beyond_one: float = 250.0,
    min_units_per_warehouse_monthly_flow: float = 100.0,
    min_units_per_warehouse_when_three_or_more_nodes: float = 500.0,
    volume_tiers_for_max_nodes: list[tuple[float, int]] | None = None,
    max_warehouses_cap: int = 6,
    candidate_pool: list[dict[str, Any]] | None = None,
    default_lane_cost_per_lb: float = 0.15,
    preserve_request_shares: bool = False,
) -> dict[str, Any]:
    """
    Returns ``selected_warehouses``, ``lanes``, ``hub_warehouse_id``, ``trace`` for downstream run.

    ``volume_tiers_for_max_nodes``: (min_monthly_demand, max_nodes_at_or_above). Example:
    [(0,1), (400,2), (1500,3), (8000,4), (40000,5), (150000,6)]
    """
    tiers = volume_tiers_for_max_nodes or [
        (0.0, 1),
        (400.0, 2),
        (1500.0, 3),
        (8000.0, 4),
        (40000.0, 5),
        (150000.0, 6),
    ]
    max_k = min(max_warehouses_cap, _max_nodes_for_monthly_volume(monthly_total_demand_units, tiers))

    pool = [dict(w) for w in (candidate_pool or default_us_candidate_warehouses())]
    by_id = {str(w.get("id") or ""): dict(w) for w in pool if w.get("id")}

    # Merge seed nodes (user primary network) into candidate universe
    for w in seed_warehouses:
        wid = str(w.get("id") or "").strip()
        if wid:
            by_id[wid] = {**by_id.get(wid, {}), **dict(w)}

    all_ids = list(by_id.keys())
    if not all_ids:
        return {
            "status": "skipped",
            "message": "no candidate or seed warehouses",
            "selected_warehouses": seed_warehouses,
            "lanes": [],
            "hub_warehouse_id": hub_warehouse_id,
            "trace": [],
        }

    hub = hub_warehouse_id or (seed_warehouses[0].get("id") if seed_warehouses else None)
    hub = str(hub or all_ids[0])

    sku_labels = [lf for lf in labels if (lf.get("sku") or "") in catalog_skus] if catalog_skus else labels
    rollup = rollup_label_demand(sku_labels, hot_pct=0.33, cold_pct=0.33)
    hot_zip3: list[str] = []
    if rollup.get("status") == "complete":
        hot_zip3 = list(rollup.get("tiers", {}).get("hot_zip3") or [])

    cars: list[CarrierCode] = ["usps", "ups", "fedex"]
    trace: list[str] = []

    if monthly_total_demand_units < min_monthly_units_to_expand_beyond_one:
        trace.append(
            f"Monthly demand {monthly_total_demand_units:.1f} < {min_monthly_units_to_expand_beyond_one:.0f} "
            "— single-node plan only."
        )
        wh_one = [by_id[hub]] if hub in by_id else [by_id[all_ids[0]]]
        return {
            "status": "complete",
            "assumptions_version": "smart_warehouse_network_v1",
            "monthly_total_demand_units": monthly_total_demand_units,
            "max_nodes_volume_tier": max_k,
            "selected_warehouse_count": 1,
            "selected_warehouses": wh_one,
            "lanes": [],
            "hub_warehouse_id": wh_one[0].get("id"),
            "label_hot_zip3_used": hot_zip3[:12],
            "rollup_status": rollup.get("status"),
            "trace": trace,
        }

    trace.append(
        "Candidate ordering uses demand-weighted mock parcel to 48 state hubs (2026 prior) + label hot-ZIP3 proxy."
    )
    trace.append(
        f"Volume tier allows up to {max_k} node(s); enforcing ≥{min_units_per_warehouse_monthly_flow:.0f} "
        f"units/mo per active node; with 3+ nodes each must clear ≥{min_units_per_warehouse_when_three_or_more_nodes:.0f}."
    )

    state_shares, label_dw_meta = build_blended_state_demand_weights_from_labels(
        labels,
        min_label_lines_for_full_blend=float(
            getattr(settings, "label_state_weight_blend_min_lines", 200.0) or 200.0
        ),
    )
    assign_mode = str(
        getattr(settings, "placement_mock_state_primary_assignment", "min_mock_parcel") or "min_mock_parcel"
    ).strip().lower()
    if assign_mode not in ("min_mock_parcel", "distance_tie_band"):
        assign_mode = "min_mock_parcel"

    # Score candidates: demand-weighted national mock (label-blended prior) + hot ZIP3 proxy
    nodes_for_grid = [{"id": wid, "postal": (by_id[wid].get("postal") or "10001")} for wid in all_ids]
    grid = build_warehouse_mock_placement_grids(
        nodes_for_grid,
        n_destinations_per_warehouse=48,
        default_weight_lb=max(0.1, weight_lb),
        state_demand_weights=state_shares,
        state_primary_assignment=assign_mode,
    )
    mean_by_wh: dict[str, float] = {}
    if grid.get("status") == "complete":
        raw = grid.get("mean_mock_parcel_usd_by_warehouse") or {}
        mean_by_wh = {str(k): float(v) for k, v in raw.items()}

    scored: list[tuple[float, str]] = []
    for wid in all_ids:
        oz = (by_id[wid].get("postal") or "10001").strip()
        dw_mock = _demand_weighted_mock_parcel_usd_from_origin(oz, max(0.1, weight_lb), cars, state_shares)
        hot = _hot_zone_last_mile_proxy(oz, hot_zip3, weight_lb=weight_lb, carriers=cars)
        combined = dw_mock + 0.25 * hot
        scored.append((combined, wid))

    scored.sort(key=lambda x: x[0])
    ordered_ids = [wid for _, wid in scored]
    # Hub first, then others by score
    rest = [w for w in ordered_ids if w != hub]
    priority = [hub] + rest if hub in by_id else ordered_ids

    best_selection: list[str] = []
    best_wh_rows: list[dict[str, Any]] = []

    for k in range(1, max_k + 1):
        take = priority[:k]
        sub = [{"id": w, "postal": by_id[w].get("postal")} for w in take]
        g2 = build_warehouse_mock_placement_grids(
            sub,
            n_destinations_per_warehouse=48,
            default_weight_lb=max(0.1, weight_lb),
            state_demand_weights=state_shares,
            state_primary_assignment=assign_mode,
        )
        if g2.get("status") != "complete":
            trace.append(f"subset size {k}: grid incomplete, stop.")
            break
        mean2 = {str(a): float(b) for a, b in (g2.get("mean_mock_parcel_usd_by_warehouse") or {}).items()}
        shares = _inverse_parcel_shares(mean2, take)
        if not _gates_allow_k_nodes(
            monthly_total_demand_units,
            take,
            shares,
            min_units_per_node=min_units_per_warehouse_monthly_flow,
            min_units_per_node_when_three_or_more_nodes=min_units_per_warehouse_when_three_or_more_nodes,
        ):
            trace.append(
                f"k={k}: rejected — min monthly flow would fall below MOQ or saturation rule "
                f"(demand={monthly_total_demand_units:.1f})."
            )
            break
        merged, _src = merge_warehouse_target_shares_for_placement(
            [{**by_id[w], "id": w, "target_share_pct": round(100.0 * shares[w], 4)} for w in take],
            g2,
            preserve_request_shares=False,
        )
        best_selection = take
        best_wh_rows = merged
        trace.append(
            f"k={k}: accepted — shares from inverse mean mock; min flow ≈ "
            f"{min(monthly_total_demand_units * shares[w] for w in take):.1f} units/mo."
        )

    if not best_selection:
        best_selection = [hub] if hub in by_id else [priority[0]]
        best_wh_rows = [dict(by_id[best_selection[0]])]

    # When the volume tier allows 2+ nodes and MOQ allows splitting across two sites, prefer ≥2 DCs.
    if (
        max_k >= 2
        and len(best_selection) == 1
        and monthly_total_demand_units >= min_monthly_units_to_expand_beyond_one
        and monthly_total_demand_units >= 2 * min_units_per_warehouse_monthly_flow
    ):
        hub_only = best_selection[0]
        for cand in priority:
            if cand == hub_only:
                continue
            take2 = [hub_only, cand]
            sub2 = [{"id": w, "postal": by_id[w].get("postal")} for w in take2]
            g2b = build_warehouse_mock_placement_grids(
                sub2,
                n_destinations_per_warehouse=48,
                default_weight_lb=max(0.1, weight_lb),
                state_demand_weights=state_shares,
                state_primary_assignment=assign_mode,
            )
            if g2b.get("status") != "complete":
                continue
            mean_b = {str(a): float(b) for a, b in (g2b.get("mean_mock_parcel_usd_by_warehouse") or {}).items()}
            shares2 = _inverse_parcel_shares(mean_b, take2)
            if _gates_allow_k_nodes(
                monthly_total_demand_units,
                take2,
                shares2,
                min_units_per_node=min_units_per_warehouse_monthly_flow,
                min_units_per_node_when_three_or_more_nodes=min_units_per_warehouse_when_three_or_more_nodes,
            ):
                merged2, _ = merge_warehouse_target_shares_for_placement(
                    [{**by_id[w], "id": w, "target_share_pct": round(100.0 * shares2[w], 4)} for w in take2],
                    g2b,
                    preserve_request_shares=False,
                )
                best_selection = take2
                best_wh_rows = merged2
                trace.append(
                    "Expanded to 2 warehouses: tier allows multi-node and per-node MOQ holds at k=2 "
                    f"(demand={monthly_total_demand_units:.1f})."
                )
                break

    h_final = (
        str(hub)
        if hub in best_selection
        else str(best_wh_rows[0].get("id") or best_selection[0])
    )

    lanes: list[dict[str, Any]] = []
    for w in best_selection:
        if str(w) != h_final:
            lanes.append(
                {"from_id": h_final, "to_id": str(w), "cost_per_lb": float(default_lane_cost_per_lb)}
            )

    return {
        "status": "complete",
        "assumptions_version": "smart_warehouse_network_v1",
        "monthly_total_demand_units": monthly_total_demand_units,
        "max_nodes_volume_tier": max_k,
        "selected_warehouse_count": len(best_selection),
        "selected_warehouses": best_wh_rows,
        "lanes": lanes,
        "hub_warehouse_id": h_final,
        "label_hot_zip3_used": hot_zip3[:12],
        "rollup_status": rollup.get("status"),
        "parameters": {
            "min_monthly_units_to_expand_beyond_one": min_monthly_units_to_expand_beyond_one,
            "min_units_per_warehouse_monthly_flow": min_units_per_warehouse_monthly_flow,
            "min_units_per_warehouse_when_three_or_more_nodes": min_units_per_warehouse_when_three_or_more_nodes,
            "candidate_scoring": "label_blended_state_demand_weighted_mock_parcel_48_hubs_plus_hot_zip3_proxy",
            "placement_mock_state_primary_assignment": assign_mode,
            "label_demand_weight_confidence": label_dw_meta.get("demand_weight_confidence"),
            "volume_tiers_for_max_nodes": tiers,
            "us_state_demand_forecast": demand_share_metadata(),
        },
        "trace": trace,
    }

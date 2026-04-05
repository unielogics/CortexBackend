"""
Greedy US warehouse network expansion: volume gates, MOQ per node, supplier-proximity primary DC
(when ``product_origin_postal`` is set), secondary DCs by contract fee proxy + demand-weighted mock
last mile, hot-ZIP3 nudge from labels, and mock parcel grids.

After DCs are selected, ``placement_mock_rate_grids`` assigns each contiguous state a primary ship-from
warehouse (min mock parcel $ among active nodes, or tie-band mode).

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
from unie_cortex.network.road_matrix import haversine_km
from unie_cortex.network.zones import CarrierCode, normalize_zip5
from unie_cortex.services.allocation_v1 import replenishment_months_for_min_transfer_batch
from unie_cortex.services.warehouse_mock_rate_grid import (
    CONTIGUOUS_STATE_HUB_DESTINATIONS_48,
    build_warehouse_mock_placement_grids,
    merge_warehouse_target_shares_for_placement,
    resolve_warehouse_lat_lon,
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
        {"id": "reg_ne", "postal": "07102", "display_name": "Northeast regional DC"},
        {"id": "reg_se", "postal": "30303", "display_name": "Southeast regional DC"},
        {"id": "reg_mw", "postal": "60607", "display_name": "Midwest regional DC"},
        {"id": "reg_tx", "postal": "77002", "display_name": "Texas / South-Central regional DC"},
        {"id": "reg_mt", "postal": "80202", "display_name": "Mountain regional DC"},
        {"id": "reg_wc", "postal": "90012", "display_name": "West Coast regional DC"},
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


def multi_dc_target_warehouse_count(
    monthly_total_demand_units: float,
    *,
    orders_per_additional: float,
    base_multi_count: int,
    max_cap: int,
) -> int:
    """
    Multi-DC scenario target: ``base_multi_count + floor(monthly / step)``, capped (e.g. 2 at 72/mo, 3 at 1000/mo).
    """
    step = max(1.0, float(orders_per_additional))
    base_m = max(2, int(base_multi_count))
    if monthly_total_demand_units <= 0:
        return min(max_cap, base_m)
    extra = int(monthly_total_demand_units // step)
    return min(max_cap, base_m + extra)


def _per_node_moq_floor(
    wid: str,
    *,
    k_nodes: int,
    by_id: dict[str, dict[str, Any]],
    default_min_1_2: float,
    default_min_3plus: float,
) -> float:
    """Use ``min_monthly_flow_units`` on the warehouse dict when set and positive; else role defaults (1–2 vs 3+ nodes)."""
    w = by_id.get(wid) or {}
    raw = w.get("min_monthly_flow_units")
    if raw is not None:
        try:
            v = float(raw)
            if v > 0:
                return v
        except (TypeError, ValueError):
            pass
    return default_min_3plus if k_nodes >= 3 else default_min_1_2


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


def _hot_zip3_from_blended_state_shares(
    state_shares: dict[str, float],
    *,
    max_states: int = 15,
) -> list[str]:
    """
    ZIP3 samples for the hot-zone parcel proxy when label tiers are empty: top demand-weighted
    contiguous states mapped to their planning hub ZIP (first three digits).
    """
    hub_rows = list(CONTIGUOUS_STATE_HUB_DESTINATIONS_48)
    ranked: list[tuple[float, str]] = []
    for m in hub_rows:
        st = str(m["state"])
        w = float(state_shares.get(st) or 0.0)
        if w <= 0:
            continue
        ranked.append((w, st))
    ranked.sort(key=lambda x: -x[0])
    out: list[str] = []
    seen: set[str] = set()
    for _w, st in ranked[:max_states]:
        row = next((r for r in hub_rows if str(r["state"]) == st), None)
        if not row:
            continue
        z5 = re.sub(r"\D", "", str(row.get("postal") or "10001"))[:5].zfill(5)
        z3 = z5[:3] if len(z5) >= 3 else ""
        if len(z3) == 3 and z3 not in seen:
            seen.add(z3)
            out.append(z3)
    return out


def _hot_zip3_for_priority_scoring(
    state_shares: dict[str, float],
    label_hot_zip3: list[str],
) -> tuple[list[str], str]:
    """Prefer label ZIP3 tiers; otherwise top states from blended (or default) demand shares."""
    if label_hot_zip3:
        return list(label_hot_zip3), "label_tiers"
    fb = _hot_zip3_from_blended_state_shares(state_shares)
    return fb, "blended_top_states"


def _km_supplier_zip_to_warehouse(origin_zip5: str, warehouse_row: dict[str, Any]) -> float | None:
    z = normalize_zip5(origin_zip5.strip())
    if not z or len(z) < 5:
        return None
    o_ll = resolve_warehouse_lat_lon({"postal": z})
    w_ll = resolve_warehouse_lat_lon(warehouse_row)
    if not o_ll or not w_ll:
        return None
    return float(haversine_km(o_ll[0], o_ll[1], w_ll[0], w_ll[1]))


def _warehouse_contract_fee_proxy_usd_per_unit(wh: dict[str, Any]) -> float:
    """Inbound + outbound + storage rate card fields on the node when present (else 0)."""

    def _f(key: str) -> float:
        v = wh.get(key)
        if v is None:
            return 0.0
        try:
            return max(0.0, float(v))
        except (TypeError, ValueError):
            return 0.0

    return (
        _f("inbound_receiving_per_unit_usd")
        + _f("outbound_handling_per_unit_usd")
        + _f("storage_per_unit_month_usd")
    )


def _secondary_warehouse_score(
    *,
    wh: dict[str, Any],
    weight_lb: float,
    cars: list[CarrierCode],
    state_shares: dict[str, float],
    hot_zip3_eff: list[str],
) -> tuple[float, float, float]:
    """Returns (weighted_total, fee_proxy, last_mile_proxy)."""
    fee = _warehouse_contract_fee_proxy_usd_per_unit(wh)
    ozp = (wh.get("postal") or "10001").strip()
    dw = _demand_weighted_mock_parcel_usd_from_origin(ozp, max(0.1, weight_lb), cars, state_shares)
    hot = _hot_zone_last_mile_proxy(ozp, hot_zip3_eff, weight_lb=weight_lb, carriers=cars)
    last_mile = dw + 0.25 * hot
    fee_w = float(getattr(settings, "smart_network_secondary_rank_contract_fee_weight", 1.0) or 1.0)
    lm_w = float(getattr(settings, "smart_network_secondary_rank_last_mile_weight", 1.0) or 1.0)
    return fee_w * fee + lm_w * last_mile, fee, last_mile


def _compute_warehouse_priority_and_hub(
    *,
    by_id: dict[str, dict[str, Any]],
    hub_warehouse_id: str | None,
    product_origin_postal: str | None,
    weight_lb: float,
    state_shares: dict[str, float],
    hot_zip3_eff: list[str],
    cars: list[CarrierCode],
) -> tuple[list[str], str, dict[str, Any]]:
    """
    Primary DC: closest to supplier ZIP when configured and origin is set; else request hub.
    Secondary+: lowest (contract fee proxy + weighted demand-weighted mock last mile).
    """
    all_ids = list(by_id.keys())
    meta: dict[str, Any] = {}
    if not all_ids:
        return [], "", meta

    hub_req = str(hub_warehouse_id or "").strip() or str(all_ids[0])
    if hub_req not in by_id:
        hub_req = str(all_ids[0])

    use_proximity = bool(getattr(settings, "smart_network_primary_dc_by_supplier_proximity", True))
    oz = normalize_zip5((product_origin_postal or "").strip()) if product_origin_postal else ""
    if not oz or len(oz) < 5:
        oz = ""

    if use_proximity and oz:
        dist_pairs: list[tuple[float, str]] = []
        for wid in all_ids:
            km = _km_supplier_zip_to_warehouse(oz, by_id[wid])
            dist_pairs.append((km if km is not None else 1.0e12, wid))
        dist_pairs.sort(key=lambda x: (x[0], x[1]))
        primary = dist_pairs[0][1]
        hub_eff = primary
        d0 = dist_pairs[0][0]
        meta["primary_dc_supplier_distance_km"] = None if d0 >= 1.0e11 else round(float(d0), 4)
        meta["warehouse_ranking_mode"] = "supplier_proximity_primary_then_fee_plus_last_mile"
        rest = [w for w in all_ids if w != primary]
        sec_scored: list[tuple[float, str]] = []
        for wid in rest:
            total, _fee, _lm = _secondary_warehouse_score(
                wh=by_id[wid],
                weight_lb=weight_lb,
                cars=cars,
                state_shares=state_shares,
                hot_zip3_eff=hot_zip3_eff,
            )
            sec_scored.append((total, wid))
        sec_scored.sort(key=lambda x: (x[0], x[1]))
        priority = [primary] + [w for _, w in sec_scored]
        return priority, hub_eff, meta

    hub_eff = hub_req
    rest = [w for w in all_ids if w != hub_eff]
    sec_scored = []
    for wid in rest:
        total, _f, _l = _secondary_warehouse_score(
            wh=by_id[wid],
            weight_lb=weight_lb,
            cars=cars,
            state_shares=state_shares,
            hot_zip3_eff=hot_zip3_eff,
        )
        sec_scored.append((total, wid))
    sec_scored.sort(key=lambda x: (x[0], x[1]))
    priority = [hub_eff] + [w for _, w in sec_scored]
    meta["warehouse_ranking_mode"] = "request_hub_first_then_fee_plus_last_mile"
    return priority, hub_eff, meta


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
    by_id: dict[str, dict[str, Any]],
    default_min_1_2: float,
    default_min_3plus: float,
) -> bool:
    """Single-node layouts always pass (baseline DC). Multi-node enforces per-warehouse MOQ or defaults."""
    if len(ids) <= 1:
        return True
    flows = _flows(demand, shares, ids)
    k = len(ids)
    for i, wid in enumerate(ids):
        floor_v = _per_node_moq_floor(
            wid,
            k_nodes=k,
            by_id=by_id,
            default_min_1_2=default_min_1_2,
            default_min_3plus=default_min_3plus,
        )
        if flows[i] + 1e-6 < floor_v:
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
    product_origin_postal: str | None = None,
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
    if volume_tiers_for_max_nodes is not None:
        max_k = min(
            max_warehouses_cap,
            _max_nodes_for_monthly_volume(monthly_total_demand_units, tiers),
        )
    else:
        step_orders = float(
            getattr(settings, "smart_network_monthly_orders_per_additional_warehouse", 1000.0) or 1000.0
        )
        base_m = int(getattr(settings, "smart_network_min_multi_dc_warehouse_count", 2) or 2)
        max_k = min(
            max_warehouses_cap,
            multi_dc_target_warehouse_count(
                monthly_total_demand_units,
                orders_per_additional=step_orders,
                base_multi_count=base_m,
                max_cap=max_warehouses_cap,
            ),
        )

    ctx = _build_warehouse_priority_order(
        seed_warehouses=seed_warehouses,
        hub_warehouse_id=hub_warehouse_id,
        labels=labels,
        catalog_skus=catalog_skus,
        weight_lb=weight_lb,
        candidate_pool=candidate_pool,
        product_origin_postal=product_origin_postal,
    )
    if ctx is None:
        return {
            "status": "skipped",
            "message": "no candidate or seed warehouses",
            "selected_warehouses": seed_warehouses,
            "lanes": [],
            "hub_warehouse_id": hub_warehouse_id,
            "trace": [],
        }

    by_id = ctx["by_id"]
    hub = str(ctx["hub"])
    priority: list[str] = list(ctx["priority"])
    hot_zip3_label = list(ctx.get("label_hot_zip3_raw") or [])
    hot_zip3_proxy = list(ctx["hot_zip3"])
    state_shares = ctx["state_shares"]
    assign_mode = str(ctx["assign_mode"])
    rollup = ctx["rollup"]
    label_dw_meta = ctx["label_dw_meta"]
    proxy_src = str(ctx.get("hot_zip3_priority_proxy_source") or "")

    trace: list[str] = []
    wrm = (ctx.get("warehouse_priority_rank_meta") or {}) if isinstance(ctx.get("warehouse_priority_rank_meta"), dict) else {}
    mode = wrm.get("warehouse_ranking_mode")
    if mode == "supplier_proximity_primary_then_fee_plus_last_mile":
        trace.append(
            "Primary DC = warehouse closest to product_origin_postal (supplier) by great-circle km on resolved lat/lon; "
            "2nd+ DCs rank by (weighted contract fee proxy: inbound+outbound+storage) + (weighted demand-weighted mock "
            f"parcel to 48 state hubs + 0.25× hot-ZIP3 proxy). hot-ZIP3 source: {proxy_src or 'n/a'}."
        )
        if wrm.get("primary_dc_supplier_distance_km") is not None:
            trace.append(f"Supplier→primary DC distance ≈ {wrm['primary_dc_supplier_distance_km']} km.")
    else:
        trace.append(
            "Primary DC = request hub_warehouse_id (or first seed); 2nd+ rank by weighted contract fee proxy + "
            f"demand-weighted mock parcel + hot-ZIP3 proxy ({proxy_src or 'n/a'})."
        )
    trace.append(
        "After DCs are chosen, each contiguous US state gets a primary ship-from among those DCs via "
        "placement_mock_rate_grids (min mock parcel $ per state; see state_shipping_coverage / rate shop summary)."
    )
    trace.append(
        f"Volume tier allows up to {max_k} node(s); enforcing per-warehouse min_monthly_flow_units when set, "
        f"else ≥{min_units_per_warehouse_monthly_flow:.0f} units/mo (1–2 nodes) / "
        f"≥{min_units_per_warehouse_when_three_or_more_nodes:.0f} (3+ nodes)."
    )

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
            by_id=by_id,
            default_min_1_2=min_units_per_warehouse_monthly_flow,
            default_min_3plus=min_units_per_warehouse_when_three_or_more_nodes,
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
                by_id=by_id,
                default_min_1_2=min_units_per_warehouse_monthly_flow,
                default_min_3plus=min_units_per_warehouse_when_three_or_more_nodes,
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
        "label_hot_zip3_used": hot_zip3_label[:12],
        "hot_zip3_priority_proxy_used": hot_zip3_proxy[:12],
        "rollup_status": rollup.get("status"),
        "parameters": {
            "min_monthly_units_to_expand_beyond_one": min_monthly_units_to_expand_beyond_one,
            "min_units_per_warehouse_monthly_flow": min_units_per_warehouse_monthly_flow,
            "min_units_per_warehouse_when_three_or_more_nodes": min_units_per_warehouse_when_three_or_more_nodes,
            "product_origin_postal_used_for_primary_dc": (str(product_origin_postal).strip() or None)
            if product_origin_postal
            else None,
            "warehouse_priority_rank_meta": ctx.get("warehouse_priority_rank_meta"),
            "hot_zip3_priority_proxy_source": proxy_src or None,
            "candidate_scoring": "supplier_proximity_primary_or_request_hub_then_fee_plus_last_mile_mock",
            "placement_mock_state_primary_assignment": assign_mode,
            "label_demand_weight_confidence": label_dw_meta.get("demand_weight_confidence"),
            "volume_tiers_for_max_nodes": tiers if volume_tiers_for_max_nodes is not None else None,
            "volume_cap_policy": (
                "monthly_orders_per_additional_warehouse"
                if volume_tiers_for_max_nodes is None
                else "explicit_volume_tiers_for_max_nodes"
            ),
            "us_state_demand_forecast": demand_share_metadata(),
        },
        "trace": trace,
    }


def _build_warehouse_priority_order(
    *,
    seed_warehouses: list[dict[str, Any]],
    hub_warehouse_id: str | None,
    labels: list[dict[str, Any]],
    catalog_skus: set[str],
    weight_lb: float,
    candidate_pool: list[dict[str, Any]] | None,
    product_origin_postal: str | None = None,
) -> dict[str, Any] | None:
    """
    Merge candidates + seeds, then rank warehouses:
    - With ``product_origin_postal`` and ``smart_network_primary_dc_by_supplier_proximity``: primary = closest DC to
      supplier ZIP; additional DCs by contract fee proxy + demand-weighted mock last mile (+ hot ZIP3 nudge).
    - Otherwise: request hub first, then same fee + last-mile score for spokes.
    State→primary ship-from per destination is delegated to ``build_warehouse_mock_placement_grids`` (min mock parcel
    among active nodes for each contiguous state).
    """
    if candidate_pool is None:
        pool = [dict(w) for w in default_us_candidate_warehouses()]
    else:
        pool = [dict(w) for w in candidate_pool]
    by_id: dict[str, dict[str, Any]] = {
        str(w.get("id") or ""): dict(w) for w in pool if w.get("id")
    }
    for w in seed_warehouses:
        wid = str(w.get("id") or "").strip()
        if wid:
            by_id[wid] = {**by_id.get(wid, {}), **dict(w)}
    all_ids = list(by_id.keys())
    if not all_ids:
        return None
    sku_labels = [lf for lf in labels if (lf.get("sku") or "") in catalog_skus] if catalog_skus else labels
    rollup = rollup_label_demand(sku_labels, hot_pct=0.33, cold_pct=0.33)
    label_hot_zip3_raw: list[str] = []
    if rollup.get("status") == "complete":
        label_hot_zip3_raw = list(rollup.get("tiers", {}).get("hot_zip3") or [])
    cars: list[CarrierCode] = ["usps", "ups", "fedex"]
    state_shares, label_dw_meta = build_blended_state_demand_weights_from_labels(
        labels,
        min_label_lines_for_full_blend=float(
            getattr(settings, "label_state_weight_blend_min_lines", 200.0) or 200.0
        ),
    )
    hot_zip3_eff, hot_proxy_src = _hot_zip3_for_priority_scoring(state_shares, label_hot_zip3_raw)
    assign_mode = str(
        getattr(settings, "placement_mock_state_primary_assignment", "min_mock_parcel") or "min_mock_parcel"
    ).strip().lower()
    if assign_mode not in ("min_mock_parcel", "distance_tie_band"):
        assign_mode = "min_mock_parcel"
    nodes_for_grid = [{"id": wid, "postal": (by_id[wid].get("postal") or "10001")} for wid in all_ids]
    build_warehouse_mock_placement_grids(
        nodes_for_grid,
        n_destinations_per_warehouse=48,
        default_weight_lb=max(0.1, weight_lb),
        state_demand_weights=state_shares,
        state_primary_assignment=assign_mode,
    )
    priority, hub, rank_meta = _compute_warehouse_priority_and_hub(
        by_id=by_id,
        hub_warehouse_id=hub_warehouse_id,
        product_origin_postal=product_origin_postal,
        weight_lb=weight_lb,
        state_shares=state_shares,
        hot_zip3_eff=hot_zip3_eff,
        cars=cars,
    )
    return {
        "by_id": by_id,
        "hub": hub,
        "priority": priority,
        "hot_zip3": hot_zip3_eff,
        "label_hot_zip3_raw": label_hot_zip3_raw,
        "hot_zip3_priority_proxy_source": hot_proxy_src,
        "state_shares": state_shares,
        "assign_mode": assign_mode,
        "rollup": rollup,
        "label_dw_meta": label_dw_meta,
        "cars": cars,
        "warehouse_priority_rank_meta": rank_meta,
    }


def _multi_dc_transfer_and_inventory_moq_guidance(
    *,
    hub_id: str,
    take: list[str],
    shares: dict[str, float],
    monthly_catalog_total: float,
    by_id: dict[str, dict[str, Any]],
    min_inter_warehouse_transfer_units: float | None,
    max_months_to_meet_min_transfer: int,
    default_min_1_2: float,
    default_min_3plus: float,
) -> dict[str, Any]:
    """
    Hub→spoke transfer batch MOQ (same as allocation) + node monthly-flow MOQ shortfall vs inventory depth.
    """
    k = len(take)
    xfer = float(min_inter_warehouse_transfer_units or 0.0)
    legs: list[dict[str, Any]] = []
    max_rm: int | None = None
    if xfer > 0 and k > 1:
        for wid in take:
            if str(wid) == str(hub_id):
                continue
            flow = monthly_catalog_total * float(shares.get(wid, 0.0))
            batch = replenishment_months_for_min_transfer_batch(
                flow,
                xfer,
                max_months=max(1, int(max_months_to_meet_min_transfer)),
            )
            rm = batch.get("recommended_replenishment_months")
            if rm is not None:
                max_rm = int(rm) if max_rm is None else max(max_rm, int(rm))
            legs.append(
                {
                    "to_warehouse_id": str(wid),
                    "monthly_flow_units": round(flow, 4),
                    "min_inter_warehouse_transfer_units": xfer,
                    "min_transfer_batch": batch,
                }
            )
    all_xfer_ok = True if not legs else all(
        (x.get("min_transfer_batch") or {}).get("feasible_within_max_months", True) for x in legs
    )

    node_floors = [
        _per_node_moq_floor(
            take[i],
            k_nodes=k,
            by_id=by_id,
            default_min_1_2=default_min_1_2,
            default_min_3plus=default_min_3plus,
        )
        for i in range(k)
    ]
    flows = _flows(monthly_catalog_total, shares, take)
    monthly_flow_moq_met = k <= 1 or all(
        flows[i] + 1e-6 >= node_floors[i] for i in range(k)
    )
    required_monthly_for_node_moq: float | None = None
    if k > 1 and not monthly_flow_moq_met and monthly_catalog_total > 0:
        ratios = []
        for i in range(k):
            sh = float(shares.get(take[i], 0.0))
            if sh > 1e-9:
                ratios.append(node_floors[i] / sh)
        if ratios:
            required_monthly_for_node_moq = max(ratios)

    approx_units_for_max_transfer_window = (
        round(monthly_catalog_total * max_rm, 2)
        if monthly_catalog_total > 0 and max_rm is not None and max_rm >= 1
        else None
    )

    return {
        "monthly_flow_moq_met_at_velocity": monthly_flow_moq_met,
        "node_monthly_flow_detail": [
            {
                "warehouse_id": take[i],
                "implied_monthly_flow_units": round(flows[i], 4),
                "moq_floor_units": round(node_floors[i], 4),
            }
            for i in range(k)
        ],
        "required_monthly_catalog_units_for_node_flow_moq": (
            round(required_monthly_for_node_moq, 2) if required_monthly_for_node_moq is not None else None
        ),
        "hub_spoke_transfer_moq_legs": legs,
        "max_replenishment_months_for_min_transfer_batch": max_rm if legs else None,
        "transfer_batch_moq_feasible_within_horizon": all_xfer_ok,
        "approx_network_units_in_max_batch_window": approx_units_for_max_transfer_window,
    }


def build_warehouse_network_recommendation_options(
    *,
    monthly_total_demand_units: float,
    seed_warehouses: list[dict[str, Any]],
    hub_warehouse_id: str | None,
    labels: list[dict[str, Any]],
    catalog_skus: set[str],
    weight_lb: float,
    min_units_per_warehouse_monthly_flow: float = 100.0,
    min_units_per_warehouse_when_three_or_more_nodes: float = 500.0,
    max_warehouses_cap: int = 6,
    candidate_pool: list[dict[str, Any]] | None = None,
    default_lane_cost_per_lb: float = 0.15,
    min_inter_warehouse_transfer_units: float | None = None,
    max_months_to_meet_min_transfer: int | None = None,
    product_origin_postal: str | None = None,
) -> dict[str, Any]:
    """
    Always returns a **single-DC** and a **multi-DC** scenario for UI / planning.

    Multi-DC target count follows ``multi_dc_target_warehouse_count`` (default: 2 + floor(monthly/1000), max 6).
    When per-node monthly-flow MOQ is not met at stated velocity, the multi option still returns with
    ``feasible: false`` but adds **transfer-batch MOQ** guidance (months of stocking to clear hub→spoke min move)
    using the same math as ``allocate_skus`` when ``min_inter_warehouse_transfer_units`` is set.
    """
    xfer_setting = (
        min_inter_warehouse_transfer_units
        if min_inter_warehouse_transfer_units is not None
        else float(getattr(settings, "placement_min_inter_warehouse_transfer_units", 100.0) or 0.0)
    )
    max_m_xfer = (
        max_months_to_meet_min_transfer
        if max_months_to_meet_min_transfer is not None
        else int(getattr(settings, "placement_max_months_min_transfer_horizon", 12) or 12)
    )
    min_xfer_effective = float(xfer_setting) if float(xfer_setting) > 0 else None

    step_orders = float(
        getattr(settings, "smart_network_monthly_orders_per_additional_warehouse", 1000.0) or 1000.0
    )
    base_m = int(getattr(settings, "smart_network_min_multi_dc_warehouse_count", 2) or 2)
    target_multi_k = multi_dc_target_warehouse_count(
        monthly_total_demand_units,
        orders_per_additional=step_orders,
        base_multi_count=base_m,
        max_cap=max_warehouses_cap,
    )

    ctx = _build_warehouse_priority_order(
        seed_warehouses=seed_warehouses,
        hub_warehouse_id=hub_warehouse_id,
        labels=labels,
        catalog_skus=catalog_skus,
        weight_lb=weight_lb,
        candidate_pool=candidate_pool,
        product_origin_postal=product_origin_postal,
    )
    if ctx is None:
        return {
            "status": "skipped",
            "message": "no candidate or seed warehouses",
            "monthly_total_demand_units": monthly_total_demand_units,
            "options": [],
        }

    by_id = ctx["by_id"]
    hub = str(ctx["hub"])
    priority: list[str] = list(ctx["priority"])
    state_shares = ctx["state_shares"]
    assign_mode = ctx["assign_mode"]
    hot_zip3_label = list(ctx.get("label_hot_zip3_raw") or [])
    hot_zip3_proxy = list(ctx["hot_zip3"])
    proxy_src = str(ctx.get("hot_zip3_priority_proxy_source") or "")
    rollup = ctx["rollup"]
    label_dw_meta = ctx["label_dw_meta"]
    wh_rank_meta = ctx.get("warehouse_priority_rank_meta")

    h_use = hub if hub in by_id else priority[0]
    wh_single = dict(by_id[h_use])
    wh_single = {**wh_single, "id": h_use, "target_share_pct": 100.0}
    opt_single: dict[str, Any] = {
        "option_key": "single_dc",
        "label": "Single warehouse (full stock at one DC)",
        "target_warehouse_count": 1,
        "feasible": True,
        "selected_warehouse_count": 1,
        "selected_warehouses": [wh_single],
        "lanes": [],
        "hub_warehouse_id": h_use,
        "trace": [
            "Baseline: consolidate all catalog demand at the hub-ranked primary DC; MOQ gates do not block single-node planning."
        ],
    }

    target_multi_k = min(target_multi_k, len(priority), max_warehouses_cap)
    take_target = priority[:target_multi_k]
    multi_trace: list[str] = [
        f"Multi-DC target from volume: {target_multi_k} warehouse(s) "
        f"(base {base_m} + floor({monthly_total_demand_units:.1f} / {step_orders:.0f}), cap {max_warehouses_cap})."
    ]

    def _layout_for_take(take: list[str]) -> tuple[list[dict[str, Any]], dict[str, float], dict[str, Any] | None]:
        sub = [{"id": w, "postal": by_id[w].get("postal")} for w in take]
        g2 = build_warehouse_mock_placement_grids(
            sub,
            n_destinations_per_warehouse=48,
            default_weight_lb=max(0.1, weight_lb),
            state_demand_weights=state_shares,
            state_primary_assignment=assign_mode,
        )
        if g2.get("status") != "complete":
            return [], {}, g2
        mean2 = {str(a): float(b) for a, b in (g2.get("mean_mock_parcel_usd_by_warehouse") or {}).items()}
        shares = _inverse_parcel_shares(mean2, take)
        merged, _ = merge_warehouse_target_shares_for_placement(
            [{**by_id[w], "id": w, "target_share_pct": round(100.0 * shares[w], 4)} for w in take],
            g2,
            preserve_request_shares=False,
        )
        return merged, shares, g2

    multi_feasible = False
    applied_k = 0
    applied_rows: list[dict[str, Any]] = []
    applied_shares: dict[str, float] = {}
    applied_take: list[str] = []

    for try_k in range(target_multi_k, 1, -1):
        take = priority[:try_k]
        merged, shares, g2 = _layout_for_take(take)
        if not merged or not shares:
            multi_trace.append(f"multi: k={try_k} grid incomplete.")
            continue
        if _gates_allow_k_nodes(
            monthly_total_demand_units,
            take,
            shares,
            by_id=by_id,
            default_min_1_2=min_units_per_warehouse_monthly_flow,
            default_min_3plus=min_units_per_warehouse_when_three_or_more_nodes,
        ):
            multi_feasible = True
            applied_k = try_k
            applied_rows = merged
            applied_shares = shares
            applied_take = list(take)
            multi_trace.append(
                f"multi: k={try_k} feasible — min implied flow ≈ "
                f"{min(monthly_total_demand_units * shares[w] for w in take):.1f} units/mo."
            )
            break
        flows = _flows(monthly_total_demand_units, shares, take)
        mins = [
            _per_node_moq_floor(
                take[i],
                k_nodes=len(take),
                by_id=by_id,
                default_min_1_2=min_units_per_warehouse_monthly_flow,
                default_min_3plus=min_units_per_warehouse_when_three_or_more_nodes,
            )
            for i in range(len(take))
        ]
        multi_trace.append(
            f"multi: k={try_k} fails MOQ at demand={monthly_total_demand_units:.1f} "
            f"(flows={[round(f, 2) for f in flows]} vs floors={[round(m, 2) for m in mins]})."
        )

    if not multi_feasible:
        merged, shares, _g2 = _layout_for_take(take_target)
        if not merged:
            merged = [
                {**by_id[w], "id": w, "target_share_pct": round(100.0 / len(take_target), 4)}
                for w in take_target
            ]
            shares = {w: 1.0 / len(take_target) for w in take_target}
        applied_k = len(take_target)
        applied_rows = merged
        applied_shares = shares
        applied_take = list(take_target)
        multi_trace.append(
            "multi: showing target layout at requested count despite MOQ — raise velocity, lower mins, or reduce DC count."
        )

    h_multi = h_use if h_use in applied_take else applied_take[0]
    lanes_m: list[dict[str, Any]] = []
    for w in applied_take:
        if str(w) != h_multi:
            lanes_m.append(
                {"from_id": h_multi, "to_id": str(w), "cost_per_lb": float(default_lane_cost_per_lb)}
            )

    implied_min_flow = (
        min(monthly_total_demand_units * applied_shares[w] for w in applied_take) if applied_shares else None
    )

    moq_guidance = _multi_dc_transfer_and_inventory_moq_guidance(
        hub_id=h_multi,
        take=list(applied_take),
        shares=applied_shares,
        monthly_catalog_total=monthly_total_demand_units,
        by_id=by_id,
        min_inter_warehouse_transfer_units=min_xfer_effective,
        max_months_to_meet_min_transfer=max_m_xfer,
        default_min_1_2=min_units_per_warehouse_monthly_flow,
        default_min_3plus=min_units_per_warehouse_when_three_or_more_nodes,
    )
    max_rm = moq_guidance.get("max_replenishment_months_for_min_transfer_batch")
    xfer_ok = bool(moq_guidance.get("transfer_batch_moq_feasible_within_horizon"))
    req_monthly = moq_guidance.get("required_monthly_catalog_units_for_node_flow_moq")

    opt_multi: dict[str, Any] = {
        "option_key": "multi_dc",
        "label": "Multi-warehouse (split stocking)",
        "target_warehouse_count_requested": target_multi_k,
        "applied_warehouse_count": applied_k,
        "feasible": multi_feasible,
        "selected_warehouses": applied_rows,
        "lanes": lanes_m,
        "hub_warehouse_id": h_multi,
        "implied_min_monthly_flow_per_node": round(implied_min_flow, 4) if implied_min_flow is not None else None,
        "trace": multi_trace,
        "inventory_transfer_moq_guidance": moq_guidance,
    }
    if applied_k > 1 and max_rm is not None and monthly_total_demand_units > 0:
        opt_multi["suggested_months_stock_depth_for_hub_spoke_transfer_moq"] = int(max_rm)
        opt_multi["approx_catalog_units_over_that_window"] = moq_guidance.get(
            "approx_network_units_in_max_batch_window"
        )
    if not multi_feasible:
        opt_multi["infeasibility_note"] = (
            "Modeled monthly flow per DC is below per-node MOQ at current catalog velocity — see "
            "inventory_transfer_moq_guidance.node_monthly_flow_detail."
        )
        parts = []
        if max_rm is not None and min_xfer_effective:
            approx_u = moq_guidance.get("approx_network_units_in_max_batch_window")
            approx_bit = f" ~{approx_u} catalog units over that stocking window" if approx_u is not None else ""
            parts.append(
                f"To run hub→spoke replenishment moves at ≥{min_xfer_effective:.0f} units (placement min transfer), "
                f"plan about {int(max_rm)} month(s) of demand coverage so a replenishment batch clears MOQ —{approx_bit} "
                f"at ~{monthly_total_demand_units:.0f} units/mo catalog velocity."
            )
        if xfer_ok is False and moq_guidance.get("hub_spoke_transfer_moq_legs"):
            parts.append(
                "At least one spoke cannot reach the minimum transfer batch within the configured max months — "
                "combine SKUs on the lane, lower MOQ, or raise velocity."
            )
        if req_monthly is not None:
            parts.append(
                f"Alternatively, lift monthly catalog velocity to ~{req_monthly:.0f} units/mo to clear per-node flow MOQ at these shares."
            )
        opt_multi["client_planning_nudge"] = " ".join(parts) if parts else opt_multi["infeasibility_note"]
        opt_multi["achievable_with_deeper_stocking_for_transfer_moq"] = bool(
            max_rm is not None and xfer_ok and not multi_feasible
        )

    return {
        "status": "complete",
        "assumptions_version": "warehouse_network_recommendation_options_v2",
        "monthly_total_demand_units": monthly_total_demand_units,
        "parameters": {
            "smart_network_monthly_orders_per_additional_warehouse": step_orders,
            "smart_network_min_multi_dc_warehouse_count": base_m,
            "default_min_units_per_warehouse_monthly_flow": min_units_per_warehouse_monthly_flow,
            "default_min_units_per_warehouse_when_three_or_more_nodes": min_units_per_warehouse_when_three_or_more_nodes,
            "max_warehouses_cap": max_warehouses_cap,
            "product_origin_postal_used_for_primary_dc": (str(product_origin_postal).strip() or None)
            if product_origin_postal
            else None,
            "warehouse_priority_rank_meta": wh_rank_meta,
            "label_demand_weight_confidence": label_dw_meta.get("demand_weight_confidence"),
            "placement_min_inter_warehouse_transfer_units_effective": min_xfer_effective,
            "placement_max_months_min_transfer_horizon": max_m_xfer,
            "us_state_demand_forecast": demand_share_metadata(),
            "hot_zip3_priority_proxy_source": proxy_src or None,
            "hot_zip3_priority_proxy_used": hot_zip3_proxy[:12],
        },
        "label_hot_zip3_used": hot_zip3_label[:12],
        "rollup_status": rollup.get("status"),
        "options": [opt_single, opt_multi],
    }


def trim_client_warehouse_network_to_demand(
    *,
    client_warehouses: list[dict[str, Any]],
    hub_warehouse_id: str | None,
    monthly_total_demand_units: float,
    labels: list[dict[str, Any]],
    catalog_skus: set[str],
    weight_lb: float,
    min_monthly_units_to_expand_beyond_one: float = 250.0,
    min_units_per_warehouse_monthly_flow: float = 100.0,
    min_units_per_warehouse_when_three_or_more_nodes: float = 500.0,
    max_warehouses_cap: int = 6,
    default_lane_cost_per_lb: float = 0.15,
    volume_tiers_for_max_nodes: list[tuple[float, int]] | None = None,
    product_origin_postal: str | None = None,
) -> dict[str, Any]:
    """
    Reduce **client-supplied** warehouses to a MOQ-feasible subset (same gates as ``recommend_warehouse_network``).

    Rankings use only client nodes (``candidate_pool=[]``): primary DC closest to ``product_origin_postal`` when set
    and settings allow; else request hub first; additional nodes by contract fee proxy + demand-weighted mock last mile.
    State→primary ship-from is still chosen in ``placement_mock_rate_grids`` per state among active nodes.
    """
    trace: list[str] = []
    tiers = volume_tiers_for_max_nodes or [
        (0.0, 1),
        (400.0, 2),
        (1500.0, 3),
        (8000.0, 4),
        (40000.0, 5),
        (150000.0, 6),
    ]
    if volume_tiers_for_max_nodes is not None:
        max_k_vol = min(
            max_warehouses_cap,
            _max_nodes_for_monthly_volume(monthly_total_demand_units, tiers),
        )
    else:
        step_orders = float(
            getattr(settings, "smart_network_monthly_orders_per_additional_warehouse", 1000.0) or 1000.0
        )
        base_m = int(getattr(settings, "smart_network_min_multi_dc_warehouse_count", 2) or 2)
        max_k_vol = min(
            max_warehouses_cap,
            multi_dc_target_warehouse_count(
                monthly_total_demand_units,
                orders_per_additional=step_orders,
                base_multi_count=base_m,
                max_cap=max_warehouses_cap,
            ),
        )

    by_id: dict[str, dict[str, Any]] = {}
    client_order: list[str] = []
    for w in client_warehouses:
        if not isinstance(w, dict):
            continue
        wid = str(w.get("id") or "").strip()
        if not wid:
            continue
        if wid not in by_id:
            client_order.append(wid)
        by_id[wid] = {**by_id.get(wid, {}), **dict(w)}

    if not by_id:
        return {
            "status": "skipped",
            "message": "no client warehouses with id",
            "selected_warehouses": client_warehouses,
            "lanes": [],
            "hub_warehouse_id": hub_warehouse_id,
            "trace": ["trim: skipped — empty client list"],
            "client_trim_applied": False,
        }

    hub_req = str(hub_warehouse_id or client_order[0]).strip()
    if hub_req not in by_id:
        hub_req = client_order[0]
    hub = hub_req

    if len(by_id) == 1:
        trace.append("trim: single client node — no reduction.")
        wh_one = [dict(by_id[hub])]
        return {
            "status": "complete",
            "assumptions_version": "client_warehouse_trim_v1",
            "monthly_total_demand_units": monthly_total_demand_units,
            "max_nodes_volume_tier": 1,
            "selected_warehouse_count": 1,
            "selected_warehouses": wh_one,
            "lanes": [],
            "hub_warehouse_id": hub,
            "trace": trace,
            "client_trim_applied": False,
            "trim_removed_count": 0,
        }

    seed_only = [dict(by_id[wid]) for wid in client_order if wid in by_id]
    ctx_trim = _build_warehouse_priority_order(
        seed_warehouses=seed_only,
        hub_warehouse_id=hub_req,
        labels=labels,
        catalog_skus=catalog_skus,
        weight_lb=weight_lb,
        candidate_pool=[],
        product_origin_postal=product_origin_postal,
    )
    if not ctx_trim:
        return {
            "status": "skipped",
            "message": "trim: priority build failed",
            "selected_warehouses": client_warehouses,
            "lanes": [],
            "hub_warehouse_id": hub_req,
            "trace": trace + ["trim: _build_warehouse_priority_order returned None"],
            "client_trim_applied": False,
        }

    state_shares = ctx_trim["state_shares"]
    label_dw_meta = ctx_trim["label_dw_meta"]
    rollup = ctx_trim["rollup"]
    label_hot_zip3_raw = list(ctx_trim.get("label_hot_zip3_raw") or [])
    hot_zip3_eff = list(ctx_trim["hot_zip3"])
    hot_proxy_src = str(ctx_trim.get("hot_zip3_priority_proxy_source") or "")
    assign_mode = str(ctx_trim["assign_mode"])
    priority = list(ctx_trim["priority"])
    hub = str(ctx_trim["hub"])
    rank_meta = ctx_trim.get("warehouse_priority_rank_meta") or {}
    trace.append(f"trim: warehouse_ranking_mode={rank_meta.get('warehouse_ranking_mode', 'n/a')}.")
    if rank_meta.get("primary_dc_supplier_distance_km") is not None:
        trace.append(f"trim: supplier→primary DC ≈ {rank_meta['primary_dc_supplier_distance_km']} km.")
    trace.append(
        "trim: per-state primary ship-from among kept DCs follows placement_mock_rate_grids (min mock parcel $ / state)."
    )

    max_k = min(len(priority), max_k_vol)
    trace.append(
        f"trim: volume tier allows up to {max_k_vol} node(s); evaluating k=1..{max_k} among {len(by_id)} client DC(s)."
    )
    trace.append(
        f"MOQ floors: ≥{min_units_per_warehouse_monthly_flow:.0f} units/mo per node; "
        f"with 3+ nodes ≥{min_units_per_warehouse_when_three_or_more_nodes:.0f}."
    )

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
            trace.append(f"trim: subset k={k} grid incomplete — stop.")
            break
        mean2 = {str(a): float(b) for a, b in (g2.get("mean_mock_parcel_usd_by_warehouse") or {}).items()}
        shares = _inverse_parcel_shares(mean2, take)
        if not _gates_allow_k_nodes(
            monthly_total_demand_units,
            take,
            shares,
            by_id=by_id,
            default_min_1_2=min_units_per_warehouse_monthly_flow,
            default_min_3plus=min_units_per_warehouse_when_three_or_more_nodes,
        ):
            trace.append(
                f"trim: k={k} rejected — implied monthly flow per node below MOQ at demand={monthly_total_demand_units:.1f}."
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
            f"trim: k={k} accepted — min implied flow ≈ "
            f"{min(monthly_total_demand_units * shares[w] for w in take):.1f} units/mo."
        )

    if not best_selection:
        best_selection = [hub]
        best_wh_rows = [dict(by_id[hub])]

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

    removed = len(by_id) - len(best_selection)
    if removed > 0:
        trace.append(
            f"trim: removed {removed} client DC(s) — multi-node economics need higher velocity or 60–90d cover to justify "
            "more stocking points (see planning_default_target_days_cover)."
        )

    return {
        "status": "complete",
        "assumptions_version": "client_warehouse_trim_v1",
        "monthly_total_demand_units": monthly_total_demand_units,
        "max_nodes_volume_tier": max_k_vol,
        "selected_warehouse_count": len(best_selection),
        "selected_warehouses": best_wh_rows,
        "lanes": lanes,
        "hub_warehouse_id": h_final,
        "label_hot_zip3_used": label_hot_zip3_raw[:12],
        "hot_zip3_priority_proxy_used": hot_zip3_eff[:12],
        "rollup_status": rollup.get("status"),
        "parameters": {
            "min_monthly_units_to_expand_beyond_one": min_monthly_units_to_expand_beyond_one,
            "min_units_per_warehouse_monthly_flow": min_units_per_warehouse_monthly_flow,
            "min_units_per_warehouse_when_three_or_more_nodes": min_units_per_warehouse_when_three_or_more_nodes,
            "product_origin_postal_used_for_primary_dc": (str(product_origin_postal).strip() or None)
            if product_origin_postal
            else None,
            "warehouse_priority_rank_meta": rank_meta,
            "placement_mock_state_primary_assignment": assign_mode,
            "label_demand_weight_confidence": label_dw_meta.get("demand_weight_confidence"),
            "volume_tiers_for_max_nodes": tiers,
            "us_state_demand_forecast": demand_share_metadata(),
            "hot_zip3_priority_proxy_source": hot_proxy_src,
            "hot_zip3_priority_proxy_used": hot_zip3_eff[:12],
        },
        "trace": trace,
        "client_trim_applied": removed > 0,
        "trim_removed_count": removed,
    }

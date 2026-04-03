"""
Single-hub vs allocated multi-node fulfillment comparison.

Emphasizes **intelligence**: verdicts, rankings, drivers, and recommendations —
not chart-serialization payloads.
"""

from __future__ import annotations

from typing import Any

from unie_cortex.services.item_intelligence_economics import (
    _mean_by_wh_for_sku_parcel,
    _weighted_mean_parcel_usd,
    _wh_fee_map,
    allocated_mock_parcel_usd_per_unit,
    derive_inventory_carry_metrics,
)




def _build_coverage_vs_inventory_reconciliation(
    norm: dict[str, float],
    placement_mock_rate_grids: dict[str, Any],
    ids: list[str],
) -> dict[str, Any] | None:
    if placement_mock_rate_grids.get("status") != "complete":
        return None
    geo_dw = placement_mock_rate_grids.get("geographic_routing_share_demand_weighted") or {}
    use_dw = isinstance(geo_dw, dict) and geo_dw
    geo = (
        {str(k): float(v) for k, v in geo_dw.items()}
        if use_dw
        else {str(k): float(v) for k, v in (placement_mock_rate_grids.get("geographic_routing_share_equal_states") or {}).items()}
    )
    if not geo:
        return None
    geo_key = (
        "geographic_routing_share_demand_weighted"
        if use_dw
        else "geographic_routing_share_equal_states"
    )
    rows: list[dict[str, Any]] = []
    for wid in ids:
        inv = float(norm.get(wid) or 0.0)
        g = float(geo.get(wid) or 0.0)
        delta = g - inv
        if delta > 0.02:
            interp = "geography_wants_more_share_at_this_dc_than_inventory_model"
        elif delta < -0.02:
            interp = "inventory_model_heavier_at_this_dc_than_pure_distance_routing"
        else:
            interp = "roughly_aligned"
        row = {
            "warehouse_id": wid,
            "inventory_allocation_share": round(inv, 6),
            "delta_routing_minus_inventory": round(delta, 6),
            "interpretation": interp,
        }
        row[geo_key] = round(g, 6)
        rows.append(row)
    basis = (
        "geographic_routing_share_demand_weighted: sum of state demand weights where this DC is primary under "
        "state_primary_assignment (min_mock_parcel or distance_tie_band). "
        if use_dw
        else (
            "geographic_routing_share_equal_states: each of 48 contiguous state hubs weighted equally; "
            "primary DC per state = nearest within midpoint tie band. "
        )
    )
    return {
        "assumptions_version": "coverage_vs_inventory_reconciliation_v2",
        "routing_basis_key": geo_key,
        "basis": basis + "inventory_allocation_share: normalized allocation target_share.",
        "by_warehouse": rows,
        "note": (
            "Mismatches imply stock placement / inbound splits / transfers may not match modeled last-mile routing. "
            "See placement_mock_rate_grids.state_shipping_coverage for state→DC detail."
        ),
    }


def _build_adjustable_model_inputs() -> dict[str, Any]:
    return {
        "assumptions_version": "adjustable_model_inputs_v1",
        "note": (
            "Structured levers that move modeled $/unit; SLA, dangerous goods, tax nexus, and carrier capacity "
            "constraints are out of model. Cross-check fulfillment_network_comparison.drivers and "
            "landed_cost_economics.negotiation_suggestions."
        ),
        "categories": [
            {
                "category": "network",
                "knobs": [
                    {
                        "key": "lane_cost_per_lb",
                        "effect_higher": "Raises inter-warehouse transfer $/unit (hub→spoke flows).",
                        "sources": ["lanes[].cost_per_lb", "config.smart_network_default_lane_cost_per_lb"],
                    },
                    {
                        "key": "warehouse_postal",
                        "effect_higher": "Changes mock parcel zones and which DC is primary per state.",
                        "sources": ["warehouses[].postal", "warehouse_candidate_pool"],
                    },
                    {
                        "key": "target_share_pct",
                        "effect_higher": "Shifts fee blends and inventory placement; does not change demand-weighted geography.",
                        "sources": ["warehouses[].target_share_pct", "placement_mock_rate_grids.suggested_target_share_pct_by_warehouse"],
                    },
                    {
                        "key": "smart_network_volume_gates",
                        "effect_higher": "More nodes only when monthly demand clears MOQ-style floors.",
                        "sources": ["config.smart_network_*"],
                    },
                ],
            },
            {
                "category": "parcel_mock",
                "knobs": [
                    {
                        "key": "catalog_median_weight_lb",
                        "effect_higher": "Raises mock parcel $ through DIM/weight in grid quotes.",
                        "sources": ["placement_mock_rate_grids.parcel_assumptions.weight_lb", "per-SKU weight re-mean"],
                    },
                    {
                        "key": "placement_mock_midpoint_tie_band",
                        "effect_higher": "Widens shared-state routing between DCs (distance assignment mode).",
                        "sources": ["config.placement_mock_midpoint_tie_band"],
                    },
                    {
                        "key": "placement_mock_state_primary_assignment",
                        "effect_higher": "Switches state→DC primary between min_mock_parcel and distance_tie_band.",
                        "sources": ["config.placement_mock_state_primary_assignment"],
                    },
                ],
            },
            {
                "category": "fees",
                "knobs": [
                    {
                        "key": "per_node_receiving_handling_storage",
                        "effect_higher": "Direct add to fully loaded $/unit (network blend by allocation share).",
                        "sources": [
                            "warehouses[].inbound_receiving_per_unit_usd",
                            "warehouses[].outbound_handling_per_unit_usd",
                            "warehouses[].storage_per_unit_month_usd",
                        ],
                    },
                ],
            },
            {
                "category": "label_truth",
                "knobs": [
                    {
                        "key": "avg_label_amount_usd",
                        "effect_higher": "Becomes the sole outbound ship $/unit in fully loaded when set (mock stays as benchmark only).",
                        "sources": ["sku_shipping_merged.effective.avg_label_amount_usd"],
                    },
                ],
            },
            {
                "category": "demand_geography",
                "knobs": [
                    {
                        "key": "default_state_demand_prior",
                        "effect_higher": "Shifts demand_weighted_expected_mock_parcel_usd_network toward high-share states.",
                        "sources": ["unie_cortex.network.us_state_demand_share", "config.us_state_demand_forecast_*"],
                    },
                    {
                        "key": "label_dest_postal_rollup",
                        "effect_higher": "Blends state weights toward observed label mix (see demand_weighting on grid).",
                        "sources": ["label_facts dest_postal", "config.label_state_weight_blend_min_lines"],
                    },
                ],
            },
            {
                "category": "inventory",
                "knobs": [
                    {
                        "key": "target_days_cover",
                        "effect_higher": "Raises peak/avg on-hand → storage $/unit sold.",
                        "sources": ["demand_by_sku.inventory_placement_summary"],
                    },
                ],
            },
        ],
        "cross_link": {
            "fulfillment_intelligence_drivers": "fulfillment_network_comparison.per_sku[].intelligence.drivers",
            "recommended_actions": "fulfillment_network_comparison.per_sku[].intelligence.recommended_actions",
            "negotiation_suggestions": "landed_cost_economics.negotiation_suggestions",
        },
    }


_LINE_ITEM_LABELS: tuple[tuple[str, str], ...] = (
    ("mock_outbound_parcel_usd_per_unit", "Outbound parcel mock (benchmark to 48 US hub ZIPs; not added to total if label buy rate is used)"),
    ("inter_warehouse_transfer_usd_per_unit", "Inter-warehouse linehaul (hub→node, modeled)"),
    ("label_usd_per_unit", "Observed label buy rate (0 = mock parcel carries outbound in fully loaded total)"),
    ("inbound_receiving_usd_per_unit", "Inbound receiving"),
    ("outbound_handling_usd_per_unit", "Outbound handling"),
    ("storage_usd_per_unit_sold_amortized_avg_inventory", "Storage rent (avg on-hand ÷ monthly demand)"),
)


def _side_by_side_vs_single(
    *,
    allocated_components: dict[str, float],
    allocated_total: float,
    single_components: dict[str, float],
    single_total: float,
    single_scenario_label: str,
    single_warehouse_id: str,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for key, label in _LINE_ITEM_LABELS:
        a = float(allocated_components.get(key) or 0.0)
        s = float(single_components.get(key) or 0.0)
        delta = round(a - s, 6)
        pct = round(100.0 * delta / s, 4) if abs(s) > 1e-9 else None
        rows.append(
            {
                "line_item_key": key,
                "line_item_label": label,
                "allocated_multi_node_usd_per_unit": round(a, 6),
                "single_hub_usd_per_unit": round(s, 6),
                "delta_usd_per_unit": delta,
                "interpretation": (
                    "allocated higher"
                    if delta > 1e-6
                    else ("allocated lower" if delta < -1e-6 else "same")
                ),
                "delta_pct_vs_single_hub_line": pct,
            }
        )
    tot_delta = round(allocated_total - single_total, 6)
    tot_pct = (
        round(100.0 * tot_delta / single_total, 4) if abs(single_total) > 1e-9 else None
    )
    return {
        "single_hub_warehouse_id": single_warehouse_id,
        "single_hub_scenario_label": single_scenario_label,
        "line_items_usd_per_unit": rows,
        "totals": {
            "allocated_multi_node_fully_loaded_usd_per_unit": round(allocated_total, 6),
            "single_hub_fully_loaded_usd_per_unit": round(single_total, 6),
            "delta_usd_per_unit": tot_delta,
            "interpretation": (
                "multi-node costs more per unit"
                if tot_delta > 1e-6
                else ("multi-node costs less per unit" if tot_delta < -1e-6 else "same fully loaded $/unit")
            ),
            "delta_pct_vs_single_hub_fully_loaded": tot_pct,
        },
    }


def _build_side_by_side_cost_comparison(
    *,
    alloc_comp: dict[str, float],
    alloc_total: float,
    best: dict[str, Any],
    single_rows: list[dict[str, Any]],
    configured_hub_id: str,
) -> dict[str, Any]:
    best_comp = dict(best.get("components_usd_per_unit") or {})
    out: dict[str, Any] = {
        "assumptions_version": "single_hub_vs_allocated_side_by_side_v1",
        "currency": "USD",
        "basis": "USD per unit sold at stated monthly demand; positive delta = multi-node costs more than that single-hub column.",
        "columns": {
            "allocated": "Multi-node (split stock + modeled hub→node transfers)",
            "single_hub_reference": "100% of demand ships from one DC; inter-DC transfer $/unit = 0",
        },
        "vs_cheapest_single_hub": _side_by_side_vs_single(
            allocated_components=alloc_comp,
            allocated_total=alloc_total,
            single_components=best_comp,
            single_total=float(best["fully_loaded_usd_per_unit"]),
            single_scenario_label=str(best.get("scenario_label") or ""),
            single_warehouse_id=str(best["ship_from_warehouse_id"]),
        ),
    }
    cfg_row = next(
        (r for r in single_rows if str(r.get("ship_from_warehouse_id") or "") == str(configured_hub_id)),
        None,
    )
    if cfg_row and str(cfg_row.get("ship_from_warehouse_id")) != str(best.get("ship_from_warehouse_id")):
        out["vs_configured_hub_as_single_origin"] = _side_by_side_vs_single(
            allocated_components=alloc_comp,
            allocated_total=alloc_total,
            single_components=dict(cfg_row.get("components_usd_per_unit") or {}),
            single_total=float(cfg_row["fully_loaded_usd_per_unit"]),
            single_scenario_label=str(cfg_row.get("scenario_label") or ""),
            single_warehouse_id=str(configured_hub_id),
        )
    return out


def _outbound_counted_in_total_usd(comp: dict[str, float]) -> float:
    """Single outbound customer-ship line in fully loaded: label buy rate if present, else mock benchmark."""
    lab = float(comp.get("label_usd_per_unit") or 0.0)
    if abs(lab) > 1e-12:
        return lab
    return float(comp.get("mock_outbound_parcel_usd_per_unit") or 0.0)


def _sku_label_buy_rate_usd(sku: str, sku_shipping_merged: dict[str, dict[str, Any]]) -> float | None:
    merged = sku_shipping_merged.get(str(sku)) or {}
    eff = merged.get("effective") or {}
    v = eff.get("avg_label_amount_usd")
    if v is None:
        return None
    return float(v)


def _fulfillment_cost_components(
    *,
    parcel_pu: float,
    transfer_pu: float,
    label_buy_usd: float | None,
    recv_pu: float,
    out_hand_pu: float,
    stor_pu: float,
) -> tuple[dict[str, float], float]:
    """
    Outbound customer ship counts once in ``total``: label buy rate when known, else mock parcel benchmark.
    ``label_usd_per_unit`` is non-zero only when ``avg_label_amount_usd`` is present on the SKU merge row.
    """
    has_label = label_buy_usd is not None
    label_row = round(float(label_buy_usd), 6) if has_label else 0.0
    outbound_once = float(label_buy_usd) if has_label else float(parcel_pu)
    comp = {
        "mock_outbound_parcel_usd_per_unit": round(parcel_pu, 6),
        "inter_warehouse_transfer_usd_per_unit": round(transfer_pu, 6),
        "label_usd_per_unit": label_row,
        "inbound_receiving_usd_per_unit": round(recv_pu, 6),
        "outbound_handling_usd_per_unit": round(out_hand_pu, 6),
        "storage_usd_per_unit_sold_amortized_avg_inventory": round(stor_pu, 6),
    }
    total = outbound_once + transfer_pu + recv_pu + out_hand_pu + stor_pu
    return comp, total


def build_fulfillment_network_comparison(
    allocation: dict[str, Any],
    placement_mock_rate_grids: dict[str, Any],
    sku_shipping_merged: dict[str, dict[str, Any]],
    warehouses: list[dict[str, Any]],
    *,
    default_inbound_receiving_per_unit_usd: float = 0.35,
    default_outbound_handling_per_unit_usd: float = 0.12,
    default_storage_per_unit_month_usd: float = 0.02,
    demand_by_sku: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Compare **allocated network** (blended parcel + modeled hub→node transfer) to
    **single-hub** counterfactuals (100% of demand ships from one DC; transfer $/unit = 0).

    Each SKU includes ``intelligence`` (verdict, ranked options, drivers, actions).
    """
    if allocation.get("status") != "complete":
        return {
            "status": "skipped",
            "message": "allocation not complete",
            "per_sku": [],
        }

    ids = list((allocation.get("warehouse_share_normalized") or {}).keys())
    norm = {str(k): float(v) for k, v in (allocation.get("warehouse_share_normalized") or {}).items()}
    mean_by_wh: dict[str, float] = {}
    raw_mean = placement_mock_rate_grids.get("mean_mock_parcel_usd_by_warehouse") or {}
    if isinstance(raw_mean, dict):
        mean_by_wh = {str(k): float(v) for k, v in raw_mean.items()}

    fee_map = _wh_fee_map(
        warehouses,
        default_inbound_receiving_per_unit_usd=default_inbound_receiving_per_unit_usd,
        default_outbound_handling_per_unit_usd=default_outbound_handling_per_unit_usd,
        default_storage_per_unit_month_usd=default_storage_per_unit_month_usd,
    )
    d_recv = default_inbound_receiving_per_unit_usd
    d_out = default_outbound_handling_per_unit_usd
    d_stor = default_storage_per_unit_month_usd
    for wid in ids:
        fee_map.setdefault(
            wid,
            {
                "inbound_receiving_per_unit_usd": d_recv,
                "outbound_handling_per_unit_usd": d_out,
                "storage_per_unit_month_usd": d_stor,
            },
        )

    hub_id = str(allocation.get("hub_warehouse_id") or ids[0] if ids else "")

    coverage_vs_inventory_reconciliation = _build_coverage_vs_inventory_reconciliation(
        norm, placement_mock_rate_grids, ids
    )

    pa = placement_mock_rate_grids.get("parcel_assumptions") or {}
    grid_w_lb = max(0.1, float(pa.get("weight_lb") or 2.0))
    parcel_mean_cache: dict[float, dict[str, float]] = {}

    per_sku: list[dict[str, Any]] = []

    for line in allocation.get("lines") or []:
        sku = line.get("sku")
        d = float(line.get("monthly_demand_units") or 0.0)
        if not sku or d <= 0:
            continue

        w_line = float(line.get("weight_lb_for_economics") or 0.0)
        mean_eff, parcel_w_meta = _mean_by_wh_for_sku_parcel(
            placement_mock_rate_grids, mean_by_wh, grid_w_lb, w_line, parcel_mean_cache
        )
        blended_parcel, dw_parcel_meta = allocated_mock_parcel_usd_per_unit(
            placement_mock_rate_grids, norm, mean_by_wh, mean_eff, ids
        )
        if dw_parcel_meta:
            parcel_w_meta = {**parcel_w_meta, **dw_parcel_meta}
        xfer_total = float(line.get("transfer_cost_est_usd") or 0.0)
        transfer_pu_allocated = xfer_total / d if d > 0 else 0.0
        label_buy = _sku_label_buy_rate_usd(str(sku), sku_shipping_merged)

        recv_blend = sum(norm.get(w, 0) * fee_map.get(w, {}).get("inbound_receiving_per_unit_usd", d_recv) for w in ids)
        out_blend = sum(norm.get(w, 0) * fee_map.get(w, {}).get("outbound_handling_per_unit_usd", d_out) for w in ids)
        stor_blend = sum(norm.get(w, 0) * fee_map.get(w, {}).get("storage_per_unit_month_usd", d_stor) for w in ids)
        wsum = sum(norm.get(w, 0) for w in ids) or 1.0
        recv_blend /= wsum
        out_blend /= wsum
        stor_blend /= wsum

        carry = derive_inventory_carry_metrics(str(sku), d, demand_by_sku)
        avg_oh_net = float(carry.get("avg_on_hand_units_time_weighted") or 0.0)
        peak_net = float(carry.get("peak_on_hand_units_network") or 0.0)
        stor_pu_alloc = (stor_blend * avg_oh_net / d) if d > 0 and avg_oh_net > 0 else stor_blend

        alloc_comp, alloc_total = _fulfillment_cost_components(
            parcel_pu=blended_parcel,
            transfer_pu=transfer_pu_allocated,
            label_buy_usd=label_buy,
            recv_pu=recv_blend,
            out_hand_pu=out_blend,
            stor_pu=stor_pu_alloc,
        )

        dw_single = placement_mock_rate_grids.get("demand_weighted_mock_parcel_usd_if_all_from_warehouse") or {}
        single_rows: list[dict[str, Any]] = []
        for wid in ids:
            base_dw = dw_single.get(wid)
            m_base = float(mean_by_wh.get(wid) or 0.0)
            m_eff = float(mean_eff.get(wid) or 0.0)
            if base_dw is not None and m_base > 1e-9:
                p_parcel = float(base_dw) * (m_eff / m_base)
            elif base_dw is not None:
                p_parcel = float(base_dw)
            else:
                p_parcel = m_eff
            fm = fee_map.get(wid, {})
            r_stor_w = float(fm.get("storage_per_unit_month_usd", d_stor))
            avg_single = peak_net * 0.5 if peak_net > 0 else avg_oh_net
            stor_pu_single = (r_stor_w * avg_single / d) if d > 0 and avg_single > 0 else r_stor_w
            comp, tot = _fulfillment_cost_components(
                parcel_pu=p_parcel,
                transfer_pu=0.0,
                label_buy_usd=label_buy,
                recv_pu=float(fm.get("inbound_receiving_per_unit_usd", d_recv)),
                out_hand_pu=float(fm.get("outbound_handling_per_unit_usd", d_out)),
                stor_pu=stor_pu_single,
            )
            single_rows.append(
                {
                    "scenario_id": f"single_hub__{wid}",
                    "scenario_label": f"Single hub: 100% ship from {wid}",
                    "ship_from_warehouse_id": wid,
                    "is_configured_hub": wid == hub_id,
                    "components_usd_per_unit": comp,
                    "fully_loaded_usd_per_unit": round(tot, 6),
                    "vs_allocated_delta_usd_per_unit": round(alloc_total - tot, 6),
                    "interpretation": (
                        "Allocated network costs more per unit than this single-hub option"
                        if alloc_total > tot
                        else (
                            "Allocated network costs less per unit than this single-hub option"
                            if alloc_total < tot
                            else "Same fully loaded $/unit (rounded)"
                        )
                    ),
                }
            )

        best = min(single_rows, key=lambda r: r["fully_loaded_usd_per_unit"])
        worst = max(single_rows, key=lambda r: r["fully_loaded_usd_per_unit"])

        transfer_edges: list[dict[str, Any]] = []
        for leg in line.get("transfer_from_hub") or []:
            fid = leg.get("from_warehouse_id")
            tid = leg.get("to_warehouse_id")
            if not fid or not tid:
                continue
            transfer_edges.append(
                {
                    "from_warehouse_id": str(fid),
                    "to_warehouse_id": str(tid),
                    "monthly_flow_units": float(leg.get("monthly_flow_units") or leg.get("units") or 0.0),
                    "est_linehaul_usd_month": float(leg.get("est_cost_usd") or 0.0),
                    "cost_per_lb_lane": float(leg.get("cost_per_lb_lane") or 0.0),
                }
            )

        sku_block = {
            "sku": str(sku),
            "monthly_demand_units": d,
            "hub_warehouse_id": hub_id,
            "allocated_network": {
                "scenario_id": "allocated_multi_node",
                "scenario_label": "Allocated network (split stock + hub→node transfers)",
                "warehouse_share_normalized": dict(norm),
                "components_usd_per_unit": alloc_comp,
                "fully_loaded_usd_per_unit": round(alloc_total, 6),
            },
            "single_hub_scenarios": single_rows,
            "best_single_hub_by_fully_loaded": {
                "warehouse_id": best["ship_from_warehouse_id"],
                "fully_loaded_usd_per_unit": best["fully_loaded_usd_per_unit"],
                "scenario_id": best["scenario_id"],
            },
            "single_hub_spread_usd_per_unit": round(
                worst["fully_loaded_usd_per_unit"] - best["fully_loaded_usd_per_unit"], 6
            ),
            "allocated_vs_best_single_hub_delta_usd_per_unit": round(
                alloc_total - float(best["fully_loaded_usd_per_unit"]), 6
            ),
            "side_by_side_cost_comparison": _build_side_by_side_cost_comparison(
                alloc_comp=alloc_comp,
                alloc_total=alloc_total,
                best=best,
                single_rows=single_rows,
                configured_hub_id=hub_id,
            ),
            "narrative": _comparison_narrative(alloc_total, float(best["fully_loaded_usd_per_unit"]), str(best["ship_from_warehouse_id"])),
            "inventory_carry_used_for_storage": carry,
            "inter_warehouse_flow": {
                "hub_warehouse_id": hub_id,
                "legs": transfer_edges,
                "monthly_linehaul_usd_total": round(sum(e.get("est_linehaul_usd_month", 0.0) for e in transfer_edges), 4),
            },
            "mock_parcel_weight_assumption": parcel_w_meta,
            "intelligence": _fulfillment_intelligence(
                sku=str(sku),
                alloc_total=alloc_total,
                alloc_comp=alloc_comp,
                single_rows=single_rows,
                best=best,
                hub_id=hub_id,
                monthly_demand=d,
                norm=norm,
                ids=ids,
                mean_by_wh=mean_eff,
            ),
        }
        per_sku.append(sku_block)

    n_exec_nodes = len(ids)
    inter_note: str | None = None
    if n_exec_nodes <= 1:
        inter_note = (
            "Executed network has only one stocking node — hub→spoke inter-DC linehaul is not modeled here "
            "(transfer $/unit = 0). Use multi_dc_parallel_scenario.fulfillment_network_comparison in the same response "
            "when the recommended multi-DC plan has two or more nodes."
        )

    out: dict[str, Any] = {
        "status": "complete",
        "assumptions_version": "fulfillment_network_comparison_v5_single_outbound_ship_line",
        "description": (
            "Fully loaded $/unit includes exactly one outbound customer-ship cost: observed label buy rate when "
            "avg_label_amount_usd is set, otherwise the mock parcel benchmark (demand-weighted network expectation when "
            "the grid exposes it, scaled for SKU weight). mock_outbound_parcel_usd_per_unit remains the benchmark; "
            "label_usd_per_unit is zero when mock carries the total. "
            "Transfer $/unit is zero for single-hub columns. Multi-node uses share split + hub→node lane model."
        ),
        "executed_warehouse_node_count": n_exec_nodes,
        "inter_warehouse_modeling_note": inter_note,
        "coverage_vs_inventory_reconciliation": coverage_vs_inventory_reconciliation,
        "adjustable_model_inputs": _build_adjustable_model_inputs(),
        "per_sku": per_sku,
    }
    return out


def _parcel_blend_after_share_nudge(
    norm: dict[str, float],
    mean_by_wh: dict[str, float],
    ids: list[str],
    *,
    nudge_share_points: float = 0.05,
) -> dict[str, Any] | None:
    if len(ids) < 2:
        return None
    high = max(ids, key=lambda w: float(mean_by_wh.get(w) or 0.0))
    low = min(ids, key=lambda w: float(mean_by_wh.get(w) or 0.0))
    if high == low:
        return None
    nn = {k: float(norm.get(k) or 0.0) for k in ids}
    mov = min(float(nudge_share_points), nn.get(high, 0.0), 1.0 - nn.get(low, 0.0))
    if mov <= 1e-9:
        return None
    nn[high] = nn.get(high, 0.0) - mov
    nn[low] = nn.get(low, 0.0) + mov
    s = sum(nn.values())
    if s <= 0:
        return None
    nn = {k: v / s for k, v in nn.items()}
    old_b = _weighted_mean_parcel_usd(norm, mean_by_wh, ids)
    new_b = _weighted_mean_parcel_usd(nn, mean_by_wh, ids)
    return {
        "description": (
            f"Illustrative: move {round(100 * mov, 2)} share points from higher-mean parcel node {high} "
            f"toward lower-mean {low} (re-run allocation + ops plan before executing)."
        ),
        "mock_parcel_blended_before_usd_per_unit": round(old_b, 6),
        "mock_parcel_blended_after_usd_per_unit": round(new_b, 6),
        "mock_parcel_delta_usd_per_unit": round(new_b - old_b, 6),
    }


def _beat_single_hub_playbook(
    *,
    sku: str,
    gap_allocated_minus_best: float,
    xfer_pu: float,
    parcel_allocated: float,
    parcel_best_single: float,
    best_wh: str,
) -> dict[str, Any]:
    """
    ``gap`` > 0 means allocated fully-loaded cost is **higher** than best single hub (must improve to win).
    """
    gap = float(gap_allocated_minus_best)
    xfer = float(xfer_pu)
    residual_after_zero_transfer = round(gap - xfer, 6)
    linehaul_discount_pct_to_close_gap: float | None = None
    if xfer > 1e-9 and gap > 0:
        linehaul_discount_pct_to_close_gap = round(min(100.0, (gap / xfer) * 100.0), 3)

    parcel_cut_after_full_linehaul = round(max(0.0, residual_after_zero_transfer), 6)
    parcel_headroom_vs_best = round(max(0.0, parcel_allocated - parcel_best_single), 6)

    moves: list[str] = []
    if gap <= 0:
        moves.append(
            "Network split already matches or beats the cheapest single-DC strategy in this model — hold lane rates and placement."
        )
    else:
        if xfer > 1e-9:
            moves.append(
                f"Closing the ${gap:.4f}/unit gap: modeled inter-DC linehaul loads ~${xfer:.4f}/unit on each sold unit — "
                f"cut effective hub→spoke $/lb by ~{linehaul_discount_pct_to_close_gap or 0:.1f}% **if** linehaul scales linearly, "
                "or eliminate the leg via supplier/PO drops to the spoke DC."
            )
        if residual_after_zero_transfer > 0.001:
            moves.append(
                f"If transfer were fully removed, you would still need ~${parcel_cut_after_full_linehaul:.4f}/unit lower blended "
                f"outbound (parcel + placement) vs today to tie {best_wh} single-origin."
            )
        if parcel_headroom_vs_best > 0.001:
            moves.append(
                f"Allocated outbound ship cost (label or mock benchmark) is ~${parcel_headroom_vs_best:.4f}/unit above "
                f"{best_wh} single-origin — shift share toward lower-mean nodes, re-contract outbound, or improve DIM/zone profile."
            )
        moves.append(
            "Stack levers: (1) linehaul/MWB (2) inbound vendor splits to spoke (3) outbound rate shop per node — model is linear on $/lb transfer."
        )

    return {
        "gap_allocated_minus_best_single_usd_per_unit": round(gap, 6),
        "modeled_inter_dc_transfer_usd_per_unit": round(xfer, 6),
        "residual_gap_after_eliminating_all_modeled_transfer_usd_per_unit": residual_after_zero_transfer,
        "linehaul_discount_pct_to_close_gap_if_cost_scales_linearly_with_modeled_leg": linehaul_discount_pct_to_close_gap,
        "blended_parcel_cut_usd_per_unit_needed_after_full_transfer_elimination": parcel_cut_after_full_linehaul,
        "parcel_premium_allocated_vs_best_single_origin_usd_per_unit": parcel_headroom_vs_best,
        "recommended_moves_to_match_or_beat_single_hub": moves,
    }


def _fulfillment_intelligence(
    *,
    sku: str,
    alloc_total: float,
    alloc_comp: dict[str, float],
    single_rows: list[dict[str, Any]],
    best: dict[str, Any],
    hub_id: str,
    monthly_demand: float,
    norm: dict[str, float],
    ids: list[str],
    mean_by_wh: dict[str, float],
) -> dict[str, Any]:
    delta = round(alloc_total - float(best["fully_loaded_usd_per_unit"]), 6)
    xfer = float(alloc_comp.get("inter_warehouse_transfer_usd_per_unit") or 0.0)
    parcel_a = _outbound_counted_in_total_usd(alloc_comp)
    best_parcel = _outbound_counted_in_total_usd(dict(best["components_usd_per_unit"] or {}))
    xfer_share = round(xfer / alloc_total, 6) if alloc_total > 0 else 0.0
    xfer_pct_of_total = round(100.0 * xfer / alloc_total, 3) if alloc_total > 0 else 0.0

    if abs(delta) < 0.01:
        verdict = "roughly_tied"
        headline = (
            f"SKU {sku}: Allocated multi-node vs best single-hub ({best['ship_from_warehouse_id']}) are ~equal on fully loaded $/unit in this mock."
        )
    elif delta < 0:
        verdict = "allocated_favorable"
        headline = (
            f"SKU {sku}: Allocated network saves ~${-delta:.4f}/unit vs shipping everything from {best['ship_from_warehouse_id']} alone."
        )
    else:
        verdict = "single_hub_favorable"
        headline = (
            f"SKU {sku}: Fulfilling 100% from {best['ship_from_warehouse_id']} is ~${delta:.4f}/unit cheaper than the current split+transfer model."
        )

    ranked: list[dict[str, Any]] = []
    pool = [
        {
            "rank": 0,
            "option": "allocated_multi_node",
            "label": "Allocated (split + hub transfers)",
            "fully_loaded_usd_per_unit": round(alloc_total, 6),
        }
    ]
    for r in single_rows:
        pool.append(
            {
                "rank": 0,
                "option": r["scenario_id"],
                "label": r["scenario_label"],
                "fully_loaded_usd_per_unit": float(r["fully_loaded_usd_per_unit"]),
            }
        )
    pool.sort(key=lambda x: x["fully_loaded_usd_per_unit"])
    for i, p in enumerate(pool, start=1):
        p2 = dict(p)
        p2["rank"] = i
        ranked.append(p2)

    recs: list[str] = []
    if verdict == "single_hub_favorable" and xfer_pct_of_total > 1.0:
        recs.append(
            f"Inter-DC positioning costs ~{xfer_pct_of_total:.2f}% of fully loaded $/unit; validate whether split inventory is strategically required before absorbing that drag."
        )
        recs.append(
            "If you must stay multi-node, prioritize cutting effective $/lb on hub→spoke lanes or increasing transfer batch sizes so linehaul amortizes better."
        )
    elif verdict == "allocated_favorable":
        recs.append(
            "Blended outbound parcel from multiple origins is beating a single-origin strategy in this mock — protect placement shares that preserve zone advantage."
        )
    else:
        recs.append("Economics are close; operational constraints (SLA, stockout risk, inbound MOQs) should break ties, not this model alone.")

    if hub_id != best["ship_from_warehouse_id"] and verdict == "single_hub_favorable":
        recs.append(
            f"Configured hub is {hub_id} but the cheapest single-origin mock is {best['ship_from_warehouse_id']} — revisit which node should be primary if you consolidate."
        )

    playbook = _beat_single_hub_playbook(
        sku=sku,
        gap_allocated_minus_best=delta,
        xfer_pu=xfer,
        parcel_allocated=parcel_a,
        parcel_best_single=best_parcel,
        best_wh=str(best["ship_from_warehouse_id"]),
    )
    share_nudge = _parcel_blend_after_share_nudge(norm, mean_by_wh, ids, nudge_share_points=0.05)

    caveats = [
        "Mock parcel uses demand-weighted national expectation when the grid includes it; otherwise unweighted mean to 48 hubs.",
        "Real lane mix, contracts, and DIM weight will differ from mocks.",
        "Label $ uses SKU history when present, else parcel proxy — tighten with carrier data.",
        "coverage_vs_inventory_reconciliation compares routing share to allocation share; they need not match operationally.",
    ]

    monthly_linehaul = xfer * monthly_demand

    primary_actions = playbook.get("recommended_moves_to_match_or_beat_single_hub") or []
    if primary_actions:
        combined_actions = list(primary_actions)
        for r in recs:
            if r not in combined_actions:
                combined_actions.append(r)
    else:
        combined_actions = recs

    out: dict[str, Any] = {
        "verdict": verdict,
        "headline": headline,
        "ranked_fulfillment_options_by_cost": ranked,
        "drivers": {
            "inter_warehouse_transfer_usd_per_unit": round(xfer, 6),
            "inter_warehouse_transfer_share_of_fully_loaded": xfer_share,
            "inter_warehouse_transfer_percent_of_fully_loaded": xfer_pct_of_total,
            "outbound_ship_counted_once_allocated_usd_per_unit": round(parcel_a, 6),
            "outbound_ship_counted_once_best_single_hub_usd_per_unit": round(best_parcel, 6),
            "outbound_delta_allocated_minus_best_single_usd_per_unit": round(parcel_a - best_parcel, 6),
            "mock_parcel_blended_allocated_usd_per_unit": round(parcel_a, 6),
            "mock_parcel_best_single_hub_usd_per_unit": round(best_parcel, 6),
            "parcel_delta_allocated_minus_best_single_usd_per_unit": round(parcel_a - best_parcel, 6),
            "implied_monthly_linehaul_usd_at_stated_demand": round(monthly_linehaul, 4),
        },
        "beat_single_hub_playbook": playbook,
        "illustrative_share_nudge_parcel_effect": share_nudge,
        "recommended_actions": combined_actions,
        "caveats": caveats,
    }
    return out


def _comparison_narrative(alloc_total: float, best_single: float, best_wh: str) -> str:
    delta = round(alloc_total - best_single, 4)
    if abs(delta) < 0.0001:
        return (
            f"Fully loaded model: allocated network is roughly tied with the best single-hub option ({best_wh})."
        )
    if delta < 0:
        return (
            f"Fully loaded model: allocated network is ~${-delta:.4f}/unit cheaper than the best single-hub "
            f"counterfactual ({best_wh}). Splitting outbound closer to demand can outweigh inter-DC transfer."
        )
    return (
        f"Fully loaded model: allocated network is ~${delta:.4f}/unit more expensive than fulfilling everything "
        f"from {best_wh} alone in this mock — transfer and blended parcel net negative vs that single origin."
    )

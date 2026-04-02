"""
Fully loaded per-unit economics + negotiation levers for item intelligence.

Rolls mock outbound parcel (48-state grid), inter-warehouse transfer (lane $/lb),
label (SKU history / merged effective), and configurable receiving + handling into
one per-SKU view for savings conversations.
"""

from __future__ import annotations

import math
from typing import Any

from unie_cortex.network.warehouse_pricing_mock import (
    estimate_hub_crossdock_forward_usd,
    estimate_receive_fee_usd,
    get_pricing_profile,
)
from unie_cortex.services.warehouse_mock_rate_grid import (
    recompute_mean_mock_parcel_usd_by_warehouse_from_grid,
)

DEFAULT_PRICING_PROFILE_ID = "profile_nj_v1"


def _sku_dims_inches(
    sku: str,
    catalog_by_sku: dict[str, Any] | None,
    *,
    fallback_l: float = 12.0,
    fallback_w: float = 10.0,
    fallback_h: float = 8.0,
) -> tuple[float, float, float]:
    row = (catalog_by_sku or {}).get(str(sku)) or {}
    try:
        l, w, h = row.get("length_in"), row.get("width_in"), row.get("height_in")
        if l is not None and w is not None and h is not None:
            return float(l), float(w), float(h)
    except (TypeError, ValueError):
        pass
    return fallback_l, fallback_w, fallback_h


def _profile_dict_for_warehouse(
    wid: str,
    warehouses: list[dict[str, Any]],
    *,
    default_profile_id: str,
) -> dict[str, Any]:
    row = next((w for w in warehouses if str(w.get("id") or "").strip() == str(wid).strip()), None)
    pid = (row or {}).get("pricing_profile_id") or default_profile_id
    prof = get_pricing_profile(str(pid).strip() if pid else None)
    if prof:
        return prof
    return get_pricing_profile(default_profile_id) or {}


def _per_warehouse_fulfillment_breakdown(
    ids: list[str],
    norm: dict[str, float],
    mean_eff: dict[str, float],
    fee_map: dict[str, dict[str, float]],
    d_out: float,
) -> tuple[list[dict[str, Any]], float]:
    """Dual-node (N-node) outbound handling + mock parcel contribution; sums to blended benchmark × handling blend."""
    rows: list[dict[str, Any]] = []
    s = 0.0
    for wid in ids:
        sh = float(norm.get(wid) or 0.0)
        parcel_w = float(mean_eff.get(wid) or 0.0)
        han = float(fee_map.get(wid, {}).get("outbound_handling_per_unit_usd", d_out))
        contrib = sh * (parcel_w + han)
        s += contrib
        rows.append(
            {
                "warehouse_id": wid,
                "fulfillment_allocation_share": round(sh, 6),
                "mock_parcel_usd_per_unit_at_node": round(parcel_w, 6),
                "outbound_handling_usd_per_unit": round(han, 6),
                "estimated_fulfillment_handling_benchmark_usd_per_unit_sold_contribution": round(contrib, 6),
            }
        )
    return rows, s


def _wh_fee_map(
    warehouses: list[dict[str, Any]],
    *,
    default_inbound_receiving_per_unit_usd: float,
    default_outbound_handling_per_unit_usd: float,
    default_storage_per_unit_month_usd: float,
) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for w in warehouses:
        wid = str(w.get("id") or "").strip()
        if not wid:
            continue

        def pick(key: str, dflt: float) -> float:
            if key in w and w[key] is not None:
                return float(w[key])
            return dflt

        out[wid] = {
            "inbound_receiving_per_unit_usd": pick(
                "inbound_receiving_per_unit_usd", default_inbound_receiving_per_unit_usd
            ),
            "outbound_handling_per_unit_usd": pick(
                "outbound_handling_per_unit_usd", default_outbound_handling_per_unit_usd
            ),
            "storage_per_unit_month_usd": pick("storage_per_unit_month_usd", default_storage_per_unit_month_usd),
        }
    return out


def allocated_mock_parcel_usd_per_unit(
    placement_mock_rate_grids: dict[str, Any],
    norm_shares: dict[str, float],
    mean_by_wh: dict[str, float],
    mean_eff: dict[str, float],
    warehouse_ids: list[str],
) -> tuple[float, dict[str, Any] | None]:
    """
    Prefer demand-weighted national expected mock parcel when the grid exposes it; scale by SKU vs grid
    inventory blend ratio when per-SKU weight re-means warehouses.
    """
    if placement_mock_rate_grids.get("status") != "complete":
        return _weighted_mean_parcel_usd(norm_shares, mean_eff, warehouse_ids), None
    dw = placement_mock_rate_grids.get("demand_weighted_expected_mock_parcel_usd_network")
    if dw is None:
        return _weighted_mean_parcel_usd(norm_shares, mean_eff, warehouse_ids), None
    blend_legacy = _weighted_mean_parcel_usd(norm_shares, mean_by_wh, warehouse_ids)
    blend_sku = _weighted_mean_parcel_usd(norm_shares, mean_eff, warehouse_ids)
    dw_f = float(dw)
    if blend_legacy > 1e-9:
        parcel_pu = dw_f * (blend_sku / blend_legacy)
    else:
        parcel_pu = blend_sku
    meta = {
        "mock_parcel_basis": "demand_weighted_expected_network_scaled_by_sku_allocation_blend_vs_grid_baseline",
        "demand_weighted_expected_mock_parcel_usd_network_at_grid_weight": round(dw_f, 6),
        "allocation_blend_mock_parcel_at_grid_weight": round(blend_legacy, 6),
        "allocation_blend_mock_parcel_at_sku_weight": round(blend_sku, 6),
    }
    return parcel_pu, meta


def _weighted_mean_parcel_usd(
    norm_shares: dict[str, float],
    mean_by_wh: dict[str, float],
    warehouse_ids: list[str],
) -> float:
    s = 0.0
    wsum = 0.0
    for wid in warehouse_ids:
        sh = float(norm_shares.get(wid) or 0.0)
        m = float(mean_by_wh.get(wid) or 0.0)
        s += sh * m
        wsum += sh
    if wsum <= 0:
        return 0.0
    return s / wsum


def _weighted_wh_fee(
    norm_shares: dict[str, float],
    warehouse_ids: list[str],
    fee_map: dict[str, dict[str, float]],
    key: str,
) -> float:
    s = 0.0
    wsum = 0.0
    for wid in warehouse_ids:
        sh = float(norm_shares.get(wid) or 0.0)
        v = float(fee_map.get(wid, {}).get(key) or 0.0)
        s += sh * v
        wsum += sh
    if wsum <= 0:
        return 0.0
    return s / wsum


def derive_inventory_carry_metrics(
    sku: str,
    monthly_demand_units: float,
    demand_by_sku: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    Peak / time-weighted average on-hand for storage (rent) from placement cover.

    Uses **linear depletion (sawtooth)** between replenishments: average on-hand = ½ × peak.
    Cohort note: uniform exit over the cover window → ~1/cover_months of the position
    retires each month at steady state (matches monthly demand when peak = demand × cover).
    """
    inv: dict[str, Any] | None = None
    if demand_by_sku and isinstance(demand_by_sku.get(sku), dict):
        inv = (demand_by_sku[sku] or {}).get("inventory_placement_summary")
    target_days = 30.0
    peak: float | None = None
    if isinstance(inv, dict):
        try:
            target_days = float(inv.get("target_days_cover") or 30.0)
        except (TypeError, ValueError):
            target_days = 30.0
        raw_peak = inv.get("suggested_total_units_for_target_cover")
        if raw_peak is not None:
            try:
                peak = float(raw_peak)
            except (TypeError, ValueError):
                peak = None

    d = float(monthly_demand_units or 0.0)
    daily = d / 30.0 if d > 0 else 0.0
    if peak is None and daily > 0 and target_days > 0:
        peak = float(math.ceil(daily * target_days))
    peak_f = float(peak or 0.0)
    avg_on_hand = peak_f * 0.5 if peak_f > 0 else 0.0
    months_cover = target_days / 30.0 if target_days > 0 else 1.0
    cohort: dict[str, Any] | None = None
    if peak_f > 0 and months_cover > 0:
        cohort = {
            "model": "uniform_exit_over_cover_window_months",
            "cover_months": round(months_cover, 4),
            "approx_fraction_of_peak_position_retiring_per_month": round(1.0 / months_cover, 6),
            "approx_units_retiring_per_month_at_steady_state": round(peak_f / months_cover, 4),
            "note": (
                "At equilibrium, monthly outflow from the stocked position should match monthly demand; "
                "peak ≈ demand × cover_months so peak/cover_months ≈ demand."
            ),
        }
        if d > 0:
            cohort["check_vs_monthly_demand_units"] = round(d, 4)

    return {
        "sku": sku,
        "target_cover_days": round(target_days, 4),
        "peak_on_hand_units_network": int(peak_f) if peak_f > 0 and abs(peak_f - round(peak_f)) < 1e-6 else round(peak_f, 4),
        "avg_on_hand_units_time_weighted": round(avg_on_hand, 4),
        "inventory_curve_model": "linear_depletion_sawtooth_avg_equals_half_of_peak_between_receipts",
        "cohort": cohort,
    }



def _mean_by_wh_for_sku_parcel(
    placement_mock_rate_grids: dict[str, Any],
    base_mean: dict[str, float],
    grid_weight_lb: float,
    sku_weight_lb: float,
    cache: dict[float, dict[str, float]],
) -> tuple[dict[str, float], dict[str, Any]]:
    """Use grid means at catalog median weight unless SKU weight differs — then re-mean from warehouse_grids legs."""
    pa = placement_mock_rate_grids.get("parcel_assumptions") or {}
    gw = max(0.1, float(grid_weight_lb or pa.get("weight_lb") or 2.0))
    meta: dict[str, Any] = {
        "mock_parcel_grid_baseline_weight_lb": round(gw, 4),
        "mock_parcel_recomputed_for_sku_weight": False,
        "sku_weight_lb_used_for_mock_parcel": None,
    }
    sw = float(sku_weight_lb) if sku_weight_lb and sku_weight_lb > 0 else gw
    sw = max(0.1, sw)
    meta["sku_weight_lb_used_for_mock_parcel"] = round(sw, 4)
    if abs(sw - gw) < 0.01:
        return base_mean, meta
    key = round(sw, 3)
    if key not in cache:
        reco = recompute_mean_mock_parcel_usd_by_warehouse_from_grid(
            placement_mock_rate_grids, weight_lb=key
        )
        cache[key] = dict(reco) if reco else dict(base_mean)
    meta["mock_parcel_recomputed_for_sku_weight"] = True
    return cache[key], meta


def build_item_intelligence_economics(
    allocation: dict[str, Any],
    placement_mock_rate_grids: dict[str, Any],
    sku_shipping_merged: dict[str, dict[str, Any]],
    warehouses: list[dict[str, Any]],
    *,
    demand_by_sku: dict[str, Any] | None = None,
    default_inbound_receiving_per_unit_usd: float = 0.35,
    default_outbound_handling_per_unit_usd: float = 0.12,
    default_storage_per_unit_month_usd: float = 0.02,
    inbound_flow_model: str = "hub_spoke_rate_card_v1",
    default_pricing_profile_id: str = DEFAULT_PRICING_PROFILE_ID,
    catalog_by_sku: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Returns ``per_sku`` rows with ``components_usd_per_unit``, ``fully_loaded_usd_per_unit``,
    ``inventory_carry``, and ``cost_detail_for_downstream_systems`` (flat breakdown for integrators).

    Storage is **rent on average on-hand**, amortized over monthly demand: ``rate × avg_on_hand / demand``.

    ``inbound_flow_model`` (default ``hub_spoke_rate_card_v1``):
    - ``blended_legacy``: single network-blended receiving $/unit (warehouse node overrides).
    - ``hub_spoke_rate_card_v1``: supplier inbound once at ``allocation.hub_warehouse_id`` (rate card),
      cross-dock forward fees per hub→spoke leg, spoke receive per moved qty, linehaul from allocation;
      sums to explicit hub + spoke receiving; ``per_warehouse_fulfillment`` always lists N-node outbound split.
    """
    if allocation.get("status") != "complete":
        return {
            "status": "skipped",
            "message": "allocation not complete",
            "per_sku": [],
            "negotiation_suggestions": [],
        }

    ids = list((allocation.get("warehouse_share_normalized") or {}).keys())
    norm = {str(k): float(v) for k, v in (allocation.get("warehouse_share_normalized") or {}).items()}
    mean_by_wh = placement_mock_rate_grids.get("mean_mock_parcel_usd_by_warehouse") or {}
    if not isinstance(mean_by_wh, dict):
        mean_by_wh = {}

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

    per_sku: list[dict[str, Any]] = []
    agg_transfer_pu_sum = 0.0
    agg_parcel_pu_sum = 0.0
    agg_recv_pu_sum = 0.0
    n_lines = 0
    pa = placement_mock_rate_grids.get("parcel_assumptions") or {}
    grid_w_lb = max(0.1, float(pa.get("weight_lb") or 2.0))
    parcel_mean_cache: dict[float, dict[str, float]] = {}

    for line in allocation.get("lines") or []:
        sku = line.get("sku")
        d = float(line.get("monthly_demand_units") or 0.0)
        if not sku or d <= 0:
            continue

        w_lb = float(line.get("weight_lb_for_economics") or 0.0)

        mean_eff, parcel_w_meta = _mean_by_wh_for_sku_parcel(
            placement_mock_rate_grids, mean_by_wh, grid_w_lb, w_lb, parcel_mean_cache
        )
        parcel_pu, dw_parcel_meta = allocated_mock_parcel_usd_per_unit(
            placement_mock_rate_grids, norm, mean_by_wh, mean_eff, ids
        )
        if dw_parcel_meta:
            parcel_w_meta = {**parcel_w_meta, **dw_parcel_meta}
        xfer_total = float(line.get("transfer_cost_est_usd") or 0.0)
        transfer_pu = xfer_total / d if d > 0 else 0.0

        merged = sku_shipping_merged.get(str(sku)) or {}
        eff = merged.get("effective") or {}
        label_buy_raw = eff.get("avg_label_amount_usd")
        has_label_buy_rate = label_buy_raw is not None
        label_buy_float = float(label_buy_raw) if has_label_buy_rate else None
        # Outbound customer ship: one cost only — real label buy rate when known, else mock parcel benchmark.
        outbound_ship_pu = float(label_buy_float) if has_label_buy_rate else parcel_pu
        label_component_usd = round(float(label_buy_float), 6) if has_label_buy_rate else 0.0

        flow_model = (inbound_flow_model or "hub_spoke_rate_card_v1").strip().lower()
        hub_spoke = flow_model == "hub_spoke_rate_card_v1"

        per_wh_fulfill, blended_fulfillment_benchmark = _per_warehouse_fulfillment_breakdown(
            ids, norm, mean_eff, fee_map, d_out
        )

        hub_recv_pu = 0.0
        crossdock_pu = 0.0
        spoke_recv_pu = 0.0
        hub_spoke_detail: dict[str, Any] | None = None
        hub_recv_doc: dict[str, Any] = {}

        if hub_spoke:
            hub_id = str(allocation.get("hub_warehouse_id") or (ids[0] if ids else ""))
            hub_prof = _profile_dict_for_warehouse(
                hub_id, warehouses, default_profile_id=default_pricing_profile_id
            )
            ln_in, wi_in, hi_in = _sku_dims_inches(str(sku), catalog_by_sku)
            w_lb_eff = max(0.1, float(w_lb or 0.1))
            d_int = max(1, int(round(d)))
            hub_recv_doc = estimate_receive_fee_usd(
                hub_prof, qty=d_int, length_in=ln_in, width_in=wi_in, height_in=hi_in
            )
            hub_recv_pu = float(hub_recv_doc.get("receive_subtotal_usd") or 0.0) / d

            crossdock_monthly = 0.0
            spoke_recv_monthly = 0.0
            legs_detail: list[dict[str, Any]] = []
            for leg in line.get("transfer_from_hub") or []:
                m = float(leg.get("units") or leg.get("monthly_flow_units") or 0.0)
                if m <= 0:
                    continue
                to_w = str(leg.get("to_warehouse_id") or "").strip()
                mq = max(1, int(round(m)))
                spoke_prof = _profile_dict_for_warehouse(
                    to_w, warehouses, default_profile_id=default_pricing_profile_id
                )
                cd_doc = estimate_hub_crossdock_forward_usd(
                    hub_prof,
                    move_qty=mq,
                    weight_lb_per_unit=w_lb_eff,
                    length_in=ln_in,
                    width_in=wi_in,
                    height_in=hi_in,
                )
                cdu = float(cd_doc.get("total_usd") or 0.0)
                crossdock_monthly += cdu
                rs_doc = estimate_receive_fee_usd(
                    spoke_prof, qty=mq, length_in=ln_in, width_in=wi_in, height_in=hi_in
                )
                rv = float(rs_doc.get("receive_subtotal_usd") or 0.0)
                spoke_recv_monthly += rv
                legs_detail.append(
                    {
                        "to_warehouse_id": to_w,
                        "monthly_move_units_rounded": mq,
                        "crossdock_forward_usd": round(cdu, 4),
                        "destination_receive_subtotal_usd": round(rv, 4),
                        "crossdock_detail": cd_doc,
                    }
                )
            crossdock_pu = crossdock_monthly / d
            spoke_recv_pu = spoke_recv_monthly / d
            recv_pu = hub_recv_pu + spoke_recv_pu
            hub_spoke_detail = {
                "model": "hub_spoke_rate_card_v1",
                "hub_warehouse_id": hub_id,
                "default_pricing_profile_id": default_pricing_profile_id,
                "dims_in_used": {"length_in": ln_in, "width_in": wi_in, "height_in": hi_in},
                "monthly_inbound_units_through_hub": d_int,
                "hub_inbound_receive": hub_recv_doc,
                "hub_inbound_receive_usd_per_unit_sold": round(hub_recv_pu, 6),
                "hub_crossdock_forward_monthly_usd": round(crossdock_monthly, 4),
                "hub_crossdock_forward_usd_per_unit_sold": round(crossdock_pu, 6),
                "spoke_inbound_receive_monthly_usd": round(spoke_recv_monthly, 4),
                "spoke_inbound_receive_usd_per_unit_sold": round(spoke_recv_pu, 6),
                "spoke_legs": legs_detail,
                "note": (
                    "Supplier inbound once at hub (rate card). Cross-dock fees on each hub→spoke move qty; "
                    "spoke receiving on moved units only. Linehaul uses allocation lane $/lb (not LTL mock)."
                ),
            }
        else:
            recv_pu = _weighted_wh_fee(norm, ids, fee_map, "inbound_receiving_per_unit_usd")

        out_hand_pu = _weighted_wh_fee(norm, ids, fee_map, "outbound_handling_per_unit_usd")
        stor_rate_network = _weighted_wh_fee(norm, ids, fee_map, "storage_per_unit_month_usd")

        carry = derive_inventory_carry_metrics(str(sku), d, demand_by_sku)
        avg_oh = float(carry.get("avg_on_hand_units_time_weighted") or 0.0)
        stor_monthly_at_avg = stor_rate_network * avg_oh if avg_oh > 0 else 0.0
        stor_monthly_at_peak = stor_rate_network * float(carry.get("peak_on_hand_units_network") or 0.0)
        stor_pu_amortized = (stor_monthly_at_avg / d) if d > 0 else stor_rate_network

        components_rounded: dict[str, Any] = {
            "mock_outbound_parcel_usd_per_unit": round(parcel_pu, 6),
            "inter_warehouse_transfer_usd_per_unit_monthly_model": round(transfer_pu, 6),
            "label_usd_per_unit": label_component_usd,
            "inbound_receiving_usd_per_unit": round(recv_pu, 6),
            "outbound_handling_usd_per_unit": round(out_hand_pu, 6),
            "storage_usd_per_unit_sold_amortized_avg_inventory": round(stor_pu_amortized, 6),
        }
        if hub_spoke:
            components_rounded["hub_inbound_receive_usd_per_unit"] = round(hub_recv_pu, 6)
            components_rounded["hub_crossdock_forward_usd_per_unit"] = round(crossdock_pu, 6)
            components_rounded["spoke_inbound_receive_usd_per_unit_aggregate"] = round(spoke_recv_pu, 6)

        if hub_spoke:
            total_pu = (
                outbound_ship_pu
                + transfer_pu
                + hub_recv_pu
                + crossdock_pu
                + spoke_recv_pu
                + out_hand_pu
                + stor_pu_amortized
            )
        else:
            total_pu = outbound_ship_pu + transfer_pu + recv_pu + out_hand_pu + stor_pu_amortized

        xfer_monthly_usd = float(line.get("transfer_cost_est_usd") or 0.0)

        inbound_block: dict[str, Any] = {"receiving_fee_usd_per_unit_inbound": round(recv_pu, 6)}
        if hub_spoke:
            inbound_block["hub_inbound_receive_usd_per_unit_sold"] = round(hub_recv_pu, 6)
            inbound_block["spoke_inbound_receive_usd_per_unit_aggregate"] = round(spoke_recv_pu, 6)
            inbound_block["hub_crossdock_forward_usd_per_unit_sold"] = round(crossdock_pu, 6)

        wh_storage_detail = []
        peak_total = float(carry.get("peak_on_hand_units_network") or 0.0)
        for wid in ids:
            sh = float(norm.get(wid) or 0.0)
            r_stor = float(fee_map.get(wid, {}).get("storage_per_unit_month_usd", d_stor))
            peak_w = peak_total * sh if peak_total > 0 else 0.0
            avg_w = peak_w * 0.5
            wh_storage_detail.append(
                {
                    "warehouse_id": wid,
                    "allocation_share": round(sh, 6),
                    "storage_rate_usd_per_unit_in_stock_per_month": round(r_stor, 6),
                    "implied_peak_on_hand_units_at_node": round(peak_w, 4),
                    "implied_avg_on_hand_units_time_weighted_at_node": round(avg_w, 4),
                    "estimated_monthly_storage_usd_at_avg_on_hand": round(r_stor * avg_w, 6),
                }
            )

        cost_detail: dict[str, Any] = {
            "schema": "item_intelligence_cost_detail_v1",
            "sku": sku,
            "currency": "USD",
            "inbound_flow_model_applied": flow_model,
            "basis": {
                "monthly_demand_units": d,
                "weight_lb_for_linehaul_model": round(w_lb, 4) if w_lb else None,
            },
            "outbound_customer_shipment": {
                "mock_parcel_benchmark_usd_per_unit": round(parcel_pu, 6),
                "mock_parcel_weight_assumption": parcel_w_meta,
                "label_buy_rate_usd_per_unit": round(float(label_buy_float), 6) if has_label_buy_rate else None,
                "outbound_counted_in_fully_loaded_usd_per_unit": round(outbound_ship_pu, 6),
                "note": (
                    "Fully loaded includes exactly one outbound customer-ship cost: observed label buy rate when "
                    "avg_label_amount_usd is present, otherwise the mock parcel benchmark. "
                    "mock_outbound_parcel_usd_per_unit is always the benchmark; label_usd_per_unit is 0 when the mock is used for the total."
                ),
            },
            "inbound_to_network": inbound_block,
            "per_warehouse_fulfillment": {
                "rows": per_wh_fulfill,
                "sum_benchmark_fulfillment_contribution_usd_per_unit_sold": round(
                    blended_fulfillment_benchmark, 6
                ),
                "note": (
                    "Each row: fulfillment_share × (mock_parcel_at_node + outbound_handling). "
                    "Sum equals blended parcel+handling benchmark when using mocks; when label buy rate is set, "
                    "fully_loaded outbound uses label instead of this sum."
                ),
            },
            "fulfillment_handling": {
                "outbound_handling_usd_per_unit": round(out_hand_pu, 6),
            },
            "inter_warehouse_positioning": {
                "modeled_monthly_linehaul_usd_total": round(xfer_monthly_usd, 6),
                "linehaul_usd_per_unit_sold": round(transfer_pu, 6),
                "note": "Lane $/lb × weight × monthly hub→node flow; divide by demand for per-unit sold.",
            },
            "inventory_carry_storage_rent": {
                "storage_rate_usd_per_unit_in_stock_per_month_network_blend": round(stor_rate_network, 6),
                "peak_on_hand_units_network": carry.get("peak_on_hand_units_network"),
                "avg_on_hand_units_time_weighted_network": carry.get("avg_on_hand_units_time_weighted"),
                "target_cover_days": carry.get("target_cover_days"),
                "inventory_curve_model": carry.get("inventory_curve_model"),
                "cohort": carry.get("cohort"),
                "estimated_monthly_storage_usd_at_peak_on_hand_network": round(stor_monthly_at_peak, 6),
                "estimated_monthly_storage_usd_at_avg_on_hand_network": round(stor_monthly_at_avg, 6),
                "storage_usd_per_unit_sold_amortized_over_monthly_demand": round(stor_pu_amortized, 6),
                "by_warehouse_allocated_share": wh_storage_detail,
            },
            "totals": {
                "fully_loaded_usd_per_unit": round(total_pu, 6),
            },
        }
        if hub_spoke and hub_spoke_detail is not None:
            cost_detail["hub_spoke_inbound_flow"] = hub_spoke_detail

        sku_notes = (
            "Outbound ship: one line in fully loaded — label buy rate from SKU history when present, else mock parcel "
            "(demand-weighted network when grid exposes it). mock_outbound_parcel_usd_per_unit is always the benchmark; "
            "label_usd_per_unit is non-zero only when avg_label_amount_usd is set. "
            "Transfer = lane $/lb × weight × monthly hub→node flow ÷ demand. "
            "Storage = network-blend $/unit-in-stock/month × time-weighted avg on-hand ÷ monthly demand."
        )
        if hub_spoke:
            sku_notes += (
                " Hub-spoke inbound: rate-card receive at hub for full monthly demand; cross-dock + spoke receive on "
                "each hub→spoke transfer leg (see hub_spoke_inbound_flow)."
            )

        per_sku.append(
            {
                "sku": sku,
                "monthly_demand_units": d,
                "weight_lb_used": round(w_lb, 4) if w_lb else None,
                "inventory_carry": carry,
                "components_usd_per_unit": dict(components_rounded),
                "cost_detail_for_downstream_systems": cost_detail,
                "fully_loaded_usd_per_unit": round(total_pu, 6),
                "notes": sku_notes,
                "label_buy_rate_known": has_label_buy_rate,
                "mock_parcel_weight_assumption": parcel_w_meta,
            }
        )
        agg_transfer_pu_sum += transfer_pu
        agg_parcel_pu_sum += parcel_pu
        agg_recv_pu_sum += recv_pu
        n_lines += 1

    n_avg = max(n_lines, 1)
    avg_transfer = agg_transfer_pu_sum / n_avg
    avg_recv = agg_recv_pu_sum / n_avg
    avg_parcel = agg_parcel_pu_sum / n_avg

    negotiation_suggestions: list[dict[str, Any]] = []
    if n_lines:
        for pct in (5.0, 10.0):
            f = pct / 100.0
            negotiation_suggestions.append(
                {
                    "lever": "inbound_receiving_fee_per_unit",
                    "current_assumption_usd_per_unit_network_blend": round(avg_recv, 4),
                    "scenario": f"If warehouses reduce receiving by {pct:.0f}%",
                    "estimated_savings_usd_per_unit": round(avg_recv * f, 6),
                    "talk_track": (
                        f"Receiving is modeled at ~${avg_recv:.3f}/unit (network blend). "
                        f"A {pct:.0f}% concession saves ~${avg_recv * f:.3f}/unit on every inbound unit — "
                        "ask for tiered receiving or carton flat rates that amortize over your batch sizes."
                    ),
                }
            )
        negotiation_suggestions.append(
            {
                "lever": "inter_warehouse_transport_cost_per_lb",
                "current_assumption_note": "Lane cost × weight × monthly transfer flow ÷ demand.",
                "current_transfer_usd_per_unit_typical_sku_blend": round(avg_transfer, 4),
                "scenario": "If carrier reduces hub-to-node $/lb by 10%",
                "estimated_savings_usd_per_unit": round(avg_transfer * 0.10, 6),
                "talk_track": (
                    "Inter-DC linehaul is a direct multiplier on weight × flow. "
                    "Negotiate MWB/min charge, backhaul lanes, or multi-stop milk runs to cut effective $/lb."
                ),
            }
        )
        negotiation_suggestions.append(
            {
                "lever": "outbound_parcel_mock_to_48_state_hubs",
                "current_mock_parcel_usd_per_unit_typical_sku_blend": round(avg_parcel, 4),
                "scenario": "If placement shifts volume to 5% cheaper mean-zone warehouses",
                "estimated_savings_usd_per_unit": round(avg_parcel * 0.05, 6),
                "talk_track": (
                    "Mock grid assumes each SKU ships from its allocated DC to representative US hubs. "
                    "Better share allocation + carrier incentives on those lanes moves blended parcel $/unit."
                ),
            }
        )
        negotiation_suggestions.append(
            {
                "lever": "label_buy_rate_vs_benchmark",
                "scenario": "Rate-shop parcel contracts / DIM divisors",
                "talk_track": (
                    "Where label history exists, compare to benchmark rates; where not, parcel mock is a ceiling. "
                    "Negotiate carrier incentives on outbound from each node."
                ),
            }
        )

    return {
        "status": "complete",
        "assumptions_version": "item_intelligence_economics_v4_hub_spoke_optional",
        "inbound_flow_model": (inbound_flow_model or "hub_spoke_rate_card_v1").strip().lower(),
        "default_pricing_profile_id": default_pricing_profile_id,
        "default_fee_fallbacks_applied_usd_per_unit": {
            "inbound_receiving_per_unit_usd": default_inbound_receiving_per_unit_usd,
            "outbound_handling_per_unit_usd": default_outbound_handling_per_unit_usd,
            "storage_per_unit_month_usd": default_storage_per_unit_month_usd,
        },
        "per_sku": per_sku,
        "negotiation_suggestions": negotiation_suggestions,
    }

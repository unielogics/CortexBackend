"""
Fuse item-intelligence signals (allocation, mock parcel grids, landed economics) into cuOpt inputs.

Goal: cuOpt cost + demand reflect inventory placement, last-mile proxy, and warehouse fulfillment
costs—not only haversine and lane rows.
"""

from __future__ import annotations

from typing import Any


def sku_to_cube_cuft_map(alloc_inputs: list[dict[str, Any]] | None) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in alloc_inputs or []:
        sku = str(row.get("sku") or "").strip()
        if not sku:
            continue
        try:
            c = float(row.get("cube_cuft") or 0.0)
        except (TypeError, ValueError):
            c = 0.0
        if c > 0:
            out[sku] = c
    return out


def monthly_allocated_cuft_by_warehouse(
    allocation: dict[str, Any] | None,
    sku_to_cube: dict[str, float],
    *,
    default_cuft_per_unit: float = 0.25,
) -> dict[str, float]:
    """
    Sum (recommended_monthly_units × cube_cuft) per warehouse_id from allocation placement.
    """
    acc: dict[str, float] = {}
    for line in (allocation or {}).get("lines") or []:
        if not isinstance(line, dict):
            continue
        sku = str(line.get("sku") or "").strip()
        cube = float(sku_to_cube.get(sku) or 0.0)
        if cube <= 0:
            cube = max(0.01, float(default_cuft_per_unit))
        for p in line.get("placement") or []:
            if not isinstance(p, dict):
                continue
            wid = str(p.get("warehouse_id") or "").strip()
            if not wid:
                continue
            try:
                u = float(p.get("recommended_monthly_units") or 0.0)
            except (TypeError, ValueError):
                u = 0.0
            if u <= 0:
                continue
            acc[wid] = acc.get(wid, 0.0) + u * cube
    return acc


def mean_mock_parcel_usd_by_warehouse(placement_mock_rate_grids: dict[str, Any] | None) -> dict[str, float]:
    raw = (placement_mock_rate_grids or {}).get("mean_mock_parcel_usd_by_warehouse") or {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, float] = {}
    for k, v in raw.items():
        wid = str(k).strip()
        if not wid:
            continue
        try:
            out[wid] = float(v)
        except (TypeError, ValueError):
            continue
    return out


def network_max_cube_cuft(alloc_inputs: list[dict[str, Any]] | None) -> float:
    m = 0.0
    for row in alloc_inputs or []:
        try:
            c = float(row.get("cube_cuft") or 0.0)
        except (TypeError, ValueError):
            c = 0.0
        m = max(m, c)
    return m


def network_max_weight_lb(alloc_inputs: list[dict[str, Any]] | None) -> float:
    m = 0.0
    for row in alloc_inputs or []:
        try:
            w = float(row.get("weight_lb") or 0.0)
        except (TypeError, ValueError):
            w = 0.0
        m = max(m, w)
    return m


def storage_monthly_usd_by_warehouse(landed_cost_economics: dict[str, Any] | None) -> dict[str, float]:
    acc: dict[str, float] = {}
    for sku_row in (landed_cost_economics or {}).get("per_sku") or []:
        if not isinstance(sku_row, dict):
            continue
        cd = sku_row.get("cost_detail_for_downstream_systems") or {}
        if not isinstance(cd, dict):
            continue
        ic = cd.get("inventory_carry_storage_rent") or {}
        if not isinstance(ic, dict):
            continue
        for row in ic.get("by_warehouse_allocated_share") or []:
            if not isinstance(row, dict):
                continue
            wid = str(row.get("warehouse_id") or "").strip()
            if not wid:
                continue
            try:
                usd = float(row.get("estimated_monthly_storage_usd_at_avg_on_hand") or 0.0)
            except (TypeError, ValueError):
                usd = 0.0
            acc[wid] = acc.get(wid, 0.0) + usd
    return acc


def inbound_receive_monthly_usd_by_warehouse(landed_cost_economics: dict[str, Any] | None) -> dict[str, float]:
    """
    Monthly inbound receive + cross-dock + spoke receive proxies from economics (hub-spoke when present;
    else blended receiving $/u × demand × share per node).
    """
    acc: dict[str, float] = {}
    for sku_row in (landed_cost_economics or {}).get("per_sku") or []:
        if not isinstance(sku_row, dict):
            continue
        try:
            d = float(sku_row.get("monthly_demand_units") or 0.0)
        except (TypeError, ValueError):
            d = 0.0
        if d <= 0:
            continue
        cd = sku_row.get("cost_detail_for_downstream_systems") or {}
        if not isinstance(cd, dict):
            continue
        hsf = cd.get("hub_spoke_inbound_flow")
        if isinstance(hsf, dict) and hsf.get("model") == "hub_spoke_rate_card_v1":
            hub_id = str(hsf.get("hub_warehouse_id") or "").strip()
            hub_doc = hsf.get("hub_inbound_receive") or {}
            hub_u = 0.0
            if isinstance(hub_doc, dict):
                try:
                    hub_u = float(hub_doc.get("receive_subtotal_usd") or 0.0)
                except (TypeError, ValueError):
                    hub_u = 0.0
            if hub_id and hub_u > 0:
                acc[hub_id] = acc.get(hub_id, 0.0) + hub_u
            try:
                cd_m = float(hsf.get("hub_crossdock_forward_monthly_usd") or 0.0)
            except (TypeError, ValueError):
                cd_m = 0.0
            if hub_id and cd_m > 0:
                acc[hub_id] = acc.get(hub_id, 0.0) + cd_m
            try:
                sp_m = float(hsf.get("spoke_inbound_receive_monthly_usd") or 0.0)
            except (TypeError, ValueError):
                sp_m = 0.0
            for leg in hsf.get("spoke_legs") or []:
                if not isinstance(leg, dict):
                    continue
                to_w = str(leg.get("to_warehouse_id") or "").strip()
                if not to_w:
                    continue
                try:
                    lv = float(leg.get("destination_receive_subtotal_usd") or 0.0)
                except (TypeError, ValueError):
                    lv = 0.0
                if lv > 0:
                    acc[to_w] = acc.get(to_w, 0.0) + lv
            if sp_m > 0 and not (hsf.get("spoke_legs") or []):
                if hub_id:
                    acc[hub_id] = acc.get(hub_id, 0.0) + sp_m
            continue
        recv_pu = 0.0
        ib = cd.get("inbound_to_network") or {}
        if isinstance(ib, dict):
            try:
                recv_pu = float(ib.get("receiving_fee_usd_per_unit_inbound") or 0.0)
            except (TypeError, ValueError):
                recv_pu = 0.0
        pw = cd.get("per_warehouse_fulfillment") or {}
        if recv_pu <= 0 or not isinstance(pw, dict):
            continue
        for row in pw.get("rows") or []:
            if not isinstance(row, dict):
                continue
            wid = str(row.get("warehouse_id") or "").strip()
            if not wid:
                continue
            try:
                sh = float(row.get("fulfillment_allocation_share") or 0.0)
            except (TypeError, ValueError):
                sh = 0.0
            acc[wid] = acc.get(wid, 0.0) + d * recv_pu * sh
    return acc


def merge_parcel_overrides(
    mean_parcel: dict[str, float],
    overrides: dict[str, float] | None,
    *,
    observed_label_usd: dict[str, float] | None = None,
) -> tuple[dict[str, float], dict[str, Any]]:
    """Apply request overrides (rate-shop / contract / TMS label proxy). Returns (merged, meta)."""
    meta: dict[str, Any] = {"parcel_contract_overrides_applied": 0, "observed_label_buy_overrides_applied": 0}
    out = dict(mean_parcel)
    if overrides:
        for k, v in overrides.items():
            wid = str(k).strip()
            if not wid:
                continue
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            if fv >= 0:
                out[wid] = fv
                meta["parcel_contract_overrides_applied"] += 1
    if observed_label_usd:
        for k, v in observed_label_usd.items():
            wid = str(k).strip()
            if not wid:
                continue
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            if fv >= 0:
                out[wid] = fv
                meta["observed_label_buy_overrides_applied"] += 1
    return out, meta


def fulfillment_monthly_usd_proxy_by_warehouse(landed_cost_economics: dict[str, Any] | None) -> dict[str, float]:
    """
    Monthly outbound proxy: demand × per-warehouse fulfillment contribution (parcel + handling at node).
    """
    acc: dict[str, float] = {}
    for sku_row in (landed_cost_economics or {}).get("per_sku") or []:
        if not isinstance(sku_row, dict):
            continue
        try:
            d = float(sku_row.get("monthly_demand_units") or 0.0)
        except (TypeError, ValueError):
            d = 0.0
        if d <= 0:
            continue
        cd = sku_row.get("cost_detail_for_downstream_systems") or {}
        if not isinstance(cd, dict):
            continue
        pw = cd.get("per_warehouse_fulfillment") or {}
        if not isinstance(pw, dict):
            continue
        for row in pw.get("rows") or []:
            if not isinstance(row, dict):
                continue
            wid = str(row.get("warehouse_id") or "").strip()
            if not wid:
                continue
            try:
                contrib = float(
                    row.get("estimated_fulfillment_handling_benchmark_usd_per_unit_sold_contribution") or 0.0
                )
            except (TypeError, ValueError):
                contrib = 0.0
            acc[wid] = acc.get(wid, 0.0) + d * contrib
    return acc


def enrich_cuopt_warehouse_rows(
    cuopt_rows: list[dict[str, Any]],
    *,
    monthly_cuft_by_wh: dict[str, float],
    parcel_usd_by_wh: dict[str, float],
    fulfillment_monthly_usd_by_wh: dict[str, float],
    storage_monthly_usd_by_wh: dict[str, float] | None = None,
    inbound_monthly_usd_by_wh: dict[str, float] | None = None,
    network_max_cube: float | None = None,
    network_max_weight_lb_val: float | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Copy cuOpt warehouse rows and attach signals used by cuopt_scenario matrix/demand builders.
    """
    meta: dict[str, Any] = {
        "warehouses_with_allocation_cuft": 0,
        "warehouses_with_parcel_proxy": 0,
        "warehouses_with_fulfillment_monthly_proxy": 0,
        "warehouses_with_storage_monthly_proxy": 0,
        "warehouses_with_inbound_monthly_proxy": 0,
    }
    st_map = storage_monthly_usd_by_wh or {}
    ib_map = inbound_monthly_usd_by_wh or {}
    out: list[dict[str, Any]] = []
    for w in cuopt_rows:
        row = dict(w)
        wid = str(row.get("id") or "").strip()
        cu = float(monthly_cuft_by_wh.get(wid) or 0.0)
        if cu > 0:
            row["allocated_monthly_cuft"] = cu
            meta["warehouses_with_allocation_cuft"] += 1
        pv = float(parcel_usd_by_wh.get(wid) or 0.0)
        if pv > 0:
            row["mean_mock_parcel_usd"] = pv
            meta["warehouses_with_parcel_proxy"] += 1
        ov = float(fulfillment_monthly_usd_by_wh.get(wid) or 0.0)
        if ov > 0:
            row["fulfillment_monthly_usd_proxy"] = ov
            meta["warehouses_with_fulfillment_monthly_proxy"] += 1
        st = float(st_map.get(wid) or 0.0)
        if st > 0:
            row["storage_monthly_usd_proxy"] = st
            meta["warehouses_with_storage_monthly_proxy"] += 1
        ib = float(ib_map.get(wid) or 0.0)
        if ib > 0:
            row["inbound_receive_monthly_usd_proxy"] = ib
            meta["warehouses_with_inbound_monthly_proxy"] += 1
        if network_max_cube is not None and float(network_max_cube) > 0:
            row["network_max_cube_cuft"] = float(network_max_cube)
        if network_max_weight_lb_val is not None and float(network_max_weight_lb_val) > 0:
            row["network_max_weight_lb"] = float(network_max_weight_lb_val)
        out.append(row)
    return out, meta

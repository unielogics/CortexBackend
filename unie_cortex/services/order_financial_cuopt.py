"""
cuOpt tri-modal for seller order-financial planning (CSV velocity → smart network → integrated compare).

Seller optimization uses **ZIP / state demand trends** and **48-state hub rate shopping** across a **national
candidate pool** (selected DCs plus engagement + default archetypes), not only the count of smart-network
``selected_warehouses``. cuOpt therefore runs when that expanded grid exposes **≥2** DCs in
``mean_mock_parcel_usd_by_warehouse``, even if linehaul keeps a **single** active stocking node.
"""

from __future__ import annotations

import math
from typing import Any

from unie_cortex.config import Settings, settings as default_settings
from unie_cortex.services.item_intelligence_cuopt_overview import (
    build_item_intelligence_multi_dc_tri_modal,
)
from unie_cortex.services.order_financial_planning import (
    build_cuopt_warehouse_rows_for_order_planning,
)


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


def _lanes_star_from_hub(
    *,
    hub_id: str,
    warehouse_ids: list[str],
    cost_per_lb: float,
) -> list[dict[str, Any]]:
    """Hub→spoke star when national pool exceeds smart-network lane rows."""
    out: list[dict[str, Any]] = []
    for w in warehouse_ids:
        if w and w != hub_id:
            out.append(
                {
                    "from_id": hub_id,
                    "to_id": w,
                    "avg_cost_per_cuft": float(cost_per_lb),
                    "utilization_pct": 100.0,
                }
            )
    return out


def _allocation_for_cuopt(
    *,
    placement_mock_rate_grids: dict[str, Any] | None,
    warehouse_ids: list[str],
    monthly_units: int,
    sku: str = "_order_planning_blended",
) -> dict[str, Any]:
    allow = set(warehouse_ids)
    if monthly_units <= 0 or not warehouse_ids:
        return {"lines": []}
    grid = placement_mock_rate_grids if isinstance(placement_mock_rate_grids, dict) else {}
    sug = grid.get("suggested_target_share_pct_by_warehouse") or {}
    weights: dict[str, float] = {}
    if isinstance(sug, dict):
        for k, v in sug.items():
            wid = str(k).strip()
            if wid not in allow:
                continue
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            if fv > 0:
                weights[wid] = fv
    if not weights:
        n = len(warehouse_ids)
        base = monthly_units // n
        rem = monthly_units % n
        placement: list[dict[str, Any]] = []
        for i, wid in enumerate(warehouse_ids):
            u = base + (1 if i < rem else 0)
            if u > 0:
                placement.append({"warehouse_id": wid, "recommended_monthly_units": u})
        return {"lines": [{"sku": sku, "placement": placement}]}

    s = sum(weights.values())
    if s <= 0:
        return _allocation_for_cuopt(
            placement_mock_rate_grids=None,
            warehouse_ids=warehouse_ids,
            monthly_units=monthly_units,
            sku=sku,
        )
    raw = {wid: monthly_units * weights[wid] / s for wid in weights}
    floors = {wid: int(math.floor(raw[wid])) for wid in weights}
    drift = monthly_units - sum(floors.values())
    order = sorted(weights.keys(), key=lambda w: (raw[w] - floors[w]), reverse=True)
    for i in range(max(0, drift)):
        floors[order[i % len(order)]] += 1
    placement = [{"warehouse_id": w, "recommended_monthly_units": floors[w]} for w in weights if floors[w] > 0]
    return {"lines": [{"sku": sku, "placement": placement}]}


async def run_order_planning_cuopt_tri_modal(
    *,
    scenario_fbm: dict[str, Any] | None,
    placement_mock_rate_grids: dict[str, Any] | None,
    analysis: dict[str, Any] | None,
    weight_lb_per_unit: float,
    length_in: float,
    width_in: float,
    height_in: float,
    engagement_network_context: dict[str, Any] | None = None,
    cfg: Settings | None = None,
    include_overview: bool | None = None,
    include_nvidia_layer: bool | None = None,
    cuopt_enrichment: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    cfg = cfg or default_settings
    if not isinstance(scenario_fbm, dict) or str(scenario_fbm.get("status") or "") != "complete":
        return None
    net = scenario_fbm.get("warehouse_network")
    if not isinstance(net, dict):
        return None

    wh_snap, source_tag = build_cuopt_warehouse_rows_for_order_planning(
        warehouse_network=net,
        placement_mock_rate_grids=placement_mock_rate_grids,
        engagement_network_context=engagement_network_context,
        cfg=cfg,
    )
    if len(wh_snap) < 2:
        return None

    ov = (analysis or {}).get("order_velocity_enrichment") or {}
    try:
        monthly_f = float(ov.get("estimated_monthly_demand_units_for_planning") or 0.0)
    except (TypeError, ValueError):
        monthly_f = 0.0
    try:
        qty = int(scenario_fbm.get("qty") or 0)
    except (TypeError, ValueError):
        qty = 0
    monthly_units = max(1, int(round(monthly_f))) if monthly_f > 0 else max(1, qty)

    wids = [str(w["id"]) for w in wh_snap]
    hub = str(net.get("hub_warehouse_id") or "").strip() or wids[0]

    base_lanes = _lanes_for_cuopt(net.get("lanes") or [])
    covered = {(str(x["from_id"]), str(x["to_id"])) for x in base_lanes}
    cost_lb = float(getattr(cfg, "smart_network_default_lane_cost_per_lb", 0.15) or 0.15)
    extra = _lanes_star_from_hub(hub_id=hub, warehouse_ids=wids, cost_per_lb=cost_lb)
    lanes_norm = list(base_lanes)
    for L in extra:
        key = (L["from_id"], L["to_id"])
        if key not in covered:
            lanes_norm.append(L)
            covered.add(key)

    allocation = _allocation_for_cuopt(
        placement_mock_rate_grids=placement_mock_rate_grids,
        warehouse_ids=wids,
        monthly_units=monthly_units,
    )

    try:
        cube = float(length_in) * float(width_in) * float(height_in) / 1728.0
    except (TypeError, ValueError):
        cube = 0.25
    cube = max(0.01, round(cube, 4))
    alloc_inputs = [
        {
            "sku": "_order_planning_blended",
            "monthly_units": float(monthly_units),
            "weight_lb": float(weight_lb_per_unit or 0.0),
            "cube_cuft": cube,
        }
    ]

    overview_on = bool(getattr(cfg, "item_intelligence_cuopt_overview_enabled", True))
    if include_overview is not None:
        overview_on = bool(include_overview)
    nvidia_on = bool(getattr(cfg, "item_intelligence_nvidia_cuopt_enabled", True))
    if include_nvidia_layer is not None:
        nvidia_on = bool(include_nvidia_layer)

    out = await build_item_intelligence_multi_dc_tri_modal(
        warehouses=wh_snap,
        lanes=lanes_norm,
        hub_warehouse_id=hub,
        include_overview=overview_on,
        include_nvidia_layer=nvidia_on,
        solver_network_source=source_tag,
        allocation=allocation,
        placement_mock_rate_grids=placement_mock_rate_grids if isinstance(placement_mock_rate_grids, dict) else None,
        landed_cost_economics=None,
        alloc_inputs=alloc_inputs,
        cuopt_enrichment=cuopt_enrichment if isinstance(cuopt_enrichment, dict) else None,
        monthly_catalog_demand_total=float(monthly_units),
        fulfillment_network_comparison=None,
    )
    if isinstance(out, dict):
        out["seller_cuopt_context"] = {
            "schema_version": "seller_order_planning_cuopt_context_v1",
            "solver_network_source": source_tag,
            "note": (
                "cuOpt nodes follow national placement rate-shop DCs when the smart network selects fewer than "
                "two stocking nodes; fusion uses 48-state hub mock parcels and suggested share weights from the grid."
            ),
        }
    return out

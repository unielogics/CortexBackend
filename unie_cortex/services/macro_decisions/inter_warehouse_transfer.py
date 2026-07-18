"""Inter-warehouse transfer (net-flow rebalancing) engine (D2).

For each SKU, compute forward demand at each peer-connected warehouse vs
current on-hand. Where one warehouse is long and another is short,
recommend a transfer.

When 3+ source warehouses each have surplus and 3+ destinations each have
shortfall, formulate the assignment as a min-cost network-flow problem
and hand it to NVIDIA cuOpt. Until cuOpt wiring lands, this module uses a
greedy nearest-neighbor heuristic so the decision flow validates end-to-end.

Output_ref shape:
{
  "transfer_set": [
    {"from_warehouse": str, "to_warehouse": str, "sku": str,
     "quantity": int, "suggested_mode": "LTL"|"FTL"}
  ],
  "total_savings_usd": float,
  "warehouse_code": str,        # origin
  "destination_warehouse_code": str,
  "confidence": float,
  "why_narrative": str,
  "model_version": str
}
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from unie_cortex.services.decision_publisher import (
    DecisionPayload,
    publish_decisions_batch,
)
from unie_cortex.services.macro_decisions.case_pack import (
    annotate_leg_with_case_pack,
    snap_to_case_pack,
)

logger = logging.getLogger(__name__)

DEFAULT_LTL_COST_USD_PER_UNIT = 1.20
DEFAULT_HOLDING_COST_USD_PER_UNIT_PER_DAY = 0.04


async def fetch_sku_imbalance(tenant_id: str) -> dict[str, list[dict[str, Any]]]:
    """Return per-SKU on-hand and forward demand across all warehouses for a tenant."""
    from unie_cortex.services.decision_publisher import _get_session_factory

    session_factory = _get_session_factory()
    if session_factory is None:
        return {}
    async with session_factory() as session:
        rows = (
            await session.execute(
                text(
                    """
                    -- wms_entity_snapshot rows include on-hand by warehouse+SKU; the
                    -- forward demand projection (D5) feeds wms_forward_demand.
                    -- units_per_case (box integrity) is fed by the WMS snapshot;
                    -- COALESCE keeps this safe when the column/value is absent.
                    SELECT s.warehouse_code, s.sku,
                           COALESCE(s.on_hand_qty, 0) AS on_hand,
                           COALESCE(d.demand_30d, 0) AS demand_30d,
                           COALESCE(s.units_per_case, 0) AS units_per_case
                      FROM cortex_core.wms_entity_snapshot s
                      LEFT JOIN cortex_ml.wms_forward_demand d
                        ON d.tenant_id = s.tenant_id
                       AND d.warehouse_code = s.warehouse_code
                       AND d.sku = s.sku
                     WHERE s.tenant_id = :tenant_id
                       AND s.sku IS NOT NULL
                    """
                ),
                {"tenant_id": tenant_id},
            )
        ).mappings().all()
    by_sku: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_sku[r["sku"]].append(dict(r))
    return by_sku


def _greedy_rebalance(per_warehouse: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return transfer suggestions for a single SKU.

    Heuristic: rank warehouses by surplus/shortfall, pair largest surplus with
    largest shortfall until either is exhausted.
    """
    # Box integrity: the SKU ships in whole cases of `units_per_case`; the engine
    # must never break a case. `units_per_case` is per-SKU (same for every row of
    # this SKU); take the first positive value seen.
    units_per_case = 0
    for w in per_warehouse:
        upc = int(w.get("units_per_case") or 0)
        if upc > 1:
            units_per_case = upc
            break

    surplus = []
    shortfall = []
    for w in per_warehouse:
        net = int(w["on_hand"]) - int(w["demand_30d"])
        if net > 5:
            surplus.append({"warehouse_code": w["warehouse_code"], "qty": net})
        elif net < -5:
            shortfall.append({"warehouse_code": w["warehouse_code"], "qty": -net})
    surplus.sort(key=lambda x: -x["qty"])
    shortfall.sort(key=lambda x: -x["qty"])
    transfers: list[dict[str, Any]] = []
    while surplus and shortfall:
        s = surplus[0]
        d = shortfall[0]
        ideal = min(s["qty"], d["qty"])
        if ideal <= 0:
            break
        # Whole boxes available at the source surplus (never break a case, never
        # ship more boxes than the surplus holds). No-op when units_per_case<=1.
        whole_boxes_available = (
            s["qty"] // units_per_case if units_per_case > 1 else None
        )
        moved = snap_to_case_pack(ideal, units_per_case, whole_boxes_available)
        if moved <= 0:
            # Snapping to whole cases yielded nothing movable for this pair
            # (e.g. surplus < 1 full case). Retire the smaller side and continue
            # so we never spin, and never emit a broken/tiny transfer.
            if units_per_case > 1:
                logger.info(
                    "transfer: skipping %s -> %s (ideal %d < 1 case of %d units)",
                    s["warehouse_code"],
                    d["warehouse_code"],
                    ideal,
                    units_per_case,
                )
            if s["qty"] <= d["qty"]:
                surplus.pop(0)
            else:
                shortfall.pop(0)
            continue
        mode = "FTL" if moved >= 24 else "LTL"
        leg = annotate_leg_with_case_pack(
            {
                "from_warehouse": s["warehouse_code"],
                "to_warehouse": d["warehouse_code"],
                "quantity": int(moved),
                "suggested_mode": mode,
            },
            ideal_units=ideal,
            units_per_case=units_per_case,
            snapped_units=int(moved),
        )
        transfers.append(leg)
        s["qty"] -= moved
        d["qty"] -= moved
        if s["qty"] <= 0:
            surplus.pop(0)
        if d["qty"] <= 0:
            shortfall.pop(0)
    return transfers


async def run_inter_warehouse_transfer_engine(
    tenant_id: str, *, model_version: str = "transfer-v1"
) -> list[str]:
    by_sku = await fetch_sku_imbalance(tenant_id)
    if not by_sku:
        logger.info("transfer: no inventory rows for tenant %s", tenant_id)
        return []

    grouped: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {"transfers": [], "total_savings": 0.0}
    )
    for sku, per_wh in by_sku.items():
        if len(per_wh) < 2:
            continue
        transfers = _greedy_rebalance(per_wh)
        for t in transfers:
            t["sku"] = sku
            # Savings = avoided LTL split + reduced shortfall holding cost (30d)
            savings = (
                t["quantity"] * DEFAULT_LTL_COST_USD_PER_UNIT * 0.4
                + t["quantity"] * DEFAULT_HOLDING_COST_USD_PER_UNIT_PER_DAY * 14
            )
            key = (t["from_warehouse"], t["to_warehouse"])
            grouped[key]["transfers"].append(t)
            grouped[key]["total_savings"] += savings

    payloads: list[DecisionPayload] = []
    for (from_wh, to_wh), bundle in grouped.items():
        if not bundle["transfers"]:
            continue
        confidence = min(0.9, 0.6 + 0.05 * len(bundle["transfers"]))
        why = (
            f"Net-flow rebalance: {from_wh} → {to_wh} across "
            f"{len(bundle['transfers'])} SKUs; saves ~${bundle['total_savings']:.0f} "
            f"over next 14 days vs LTL splits + holding cost."
        )
        payloads.append(
            DecisionPayload(
                tenant_id=tenant_id,
                warehouse_id=from_wh,
                target_warehouse_id=from_wh,
                decision_type="inter_warehouse_transfer",
                output_ref={
                    "transfer_set": bundle["transfers"],
                    "total_savings_usd": round(bundle["total_savings"], 2),
                    "warehouse_code": from_wh,
                    "destination_warehouse_code": to_wh,
                    "confidence": confidence,
                    "why_narrative": why,
                    "model_version": model_version,
                },
                model_version=model_version,
            )
        )

    ids = await publish_decisions_batch(payloads)
    logger.info("transfer: published %d decisions for tenant %s", len(ids), tenant_id)
    return ids

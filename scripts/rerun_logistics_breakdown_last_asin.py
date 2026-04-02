"""
Rerun single-hub vs multi-node logistics breakdown for ASIN B012345678 (e2e fixture).

Seeds a minimal demand snapshot so allocation runs without relying on Keepa for this ASIN.

Usage (repo root):
  .venv\\Scripts\\python scripts\\rerun_logistics_breakdown_last_asin.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.pop("MONGODB_URI", None)

from unie_cortex.db import database as db
from unie_cortex.db.store import SqlCortexStore
from unie_cortex.services.intelligence_run import run_item_intelligence

ASIN = "B012345678"
SKU = "SKU-A"
TENANT = "logistics_rerun"
WH_HUB = "wh_east"
WH_SPOKE = "wh_west"


async def main() -> None:
    await db.init_sql_db()
    if db.SessionLocal is None:
        raise RuntimeError("SQLite session factory missing")

    derived = {
        "status": "complete",
        "sku": SKU,
        "asin": ASIN,
        "method": "manual_seed_for_demo",
        "planning_method": "manual_seed",
        "monthly_units_est_mid": 400.0,
        "monthly_units_est_low": 350.0,
        "monthly_units_est_high": 450.0,
        "inventory_placement_summary": {
            "assumptions_version": "inventory_placement_summary_v1",
            "asin": ASIN,
            "target_days_cover": 30.0,
            "monthly_units_est_mid_used": 400.0,
            "est_daily_units_from_monthly": 400.0 / 30.0,
            "suggested_total_units_for_target_cover": 400,
            "suggested_min_active_warehouses": 2,
            "warehouse_splits": [],
            "narrative_bullets": [],
        },
    }

    # One session: :memory: SQLite is per-connection; do not open a second session.
    async with db.SessionLocal() as session:
        store = SqlCortexStore(session)
        await store.sku_catalog_upsert(
            TENANT,
            {
                "sku": SKU,
                "asin": ASIN,
                "weight_lb": 2.0,
                "length_in": 10.0,
                "width_in": 8.0,
                "height_in": 6.0,
            },
        )
        await store.sku_demand_upsert(
            TENANT, ASIN, 1, derived, sku=SKU, method="manual_seed"
        )
        await session.commit()

        warehouses = [
            {"id": WH_HUB, "postal": "10001", "target_share_pct": 55.0},
            {"id": WH_SPOKE, "postal": "90001", "target_share_pct": 45.0},
        ]
        lanes = [{"from_id": WH_HUB, "to_id": WH_SPOKE, "cost_per_lb": 0.15}]
        art = await run_item_intelligence(
            store,
            TENANT,
            WH_HUB,
            warehouses=warehouses,
            lanes=lanes,
            hub_warehouse_id=WH_HUB,
            preserve_warehouse_target_shares=True,
        )
        await session.commit()

    print("=== ASIN / SKU ===")
    print(json.dumps({"asin": ASIN, "sku": SKU, "seed_monthly_units_est_mid": 400.0}, indent=2))

    dem = (art.get("demand_by_sku") or {}).get(SKU) or {}
    print("\n=== demand_by_sku (subset) ===")
    print(
        json.dumps(
            {
                "monthly_units_est_mid": dem.get("monthly_units_est_mid"),
                "status": dem.get("status"),
                "from_store": dem.get("from_store"),
            },
            indent=2,
        )
    )

    alloc = art.get("allocation") or {}
    print("\n=== allocation.status ===", alloc.get("status"), alloc.get("message"))
    lines = [ln for ln in (alloc.get("lines") or []) if ln.get("sku") == SKU]
    if lines:
        print("\n=== allocation line (trimmed) ===")
        slim = {
            k: lines[0].get(k)
            for k in (
                "sku",
                "monthly_units",
                "by_warehouse",
                "inter_warehouse_transfer_units_monthly_est",
                "network_placement_adjustment",
            )
            if k in lines[0]
        }
        print(json.dumps(slim, indent=2, default=str))

    fnc = art.get("fulfillment_network_comparison") or {}
    print("\n=== fulfillment_network_comparison.status ===", fnc.get("status"), fnc.get("message"))
    rows = [x for x in (fnc.get("per_sku") or []) if x.get("sku") == SKU]
    if not rows:
        print("(no per_sku row — check allocation / economics)")
        return

    p0 = rows[0]
    sbs = p0.get("side_by_side_cost_comparison") or {}
    print("\n=== SIDE BY SIDE: multi-node vs single hub ($/unit) ===")
    print(json.dumps(sbs, indent=2, default=str))

    intel = dict(p0.get("intelligence") or {})
    for k in ("beat_single_hub_playbook", "illustrative_share_nudge_parcel_effect"):
        intel.pop(k, None)
    print("\n=== fulfillment intelligence (trimmed) ===")
    print(json.dumps(intel, indent=2, default=str))

    if p0.get("beat_single_hub_playbook"):
        print("\n=== beat_single_hub_playbook ===")
        print(json.dumps(p0["beat_single_hub_playbook"], indent=2, default=str))

    print("\n=== inter_warehouse_flow ===")
    print(json.dumps(p0.get("inter_warehouse_flow"), indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())

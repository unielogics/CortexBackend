"""One-off / CLI: item intelligence summary for ASIN + ZIP.

  python scripts/run_item_intel_asin_zip.py B009WLPEJA 07055
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.pop("MONGODB_URI", None)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from unie_cortex.main import app
from unie_cortex.network.facility_freight_mock_defaults import enrich_warehouse_node_dict


def main() -> None:
    asin = (sys.argv[1] if len(sys.argv) > 1 else "B009WLPEJA").strip().upper()
    postal = (sys.argv[2] if len(sys.argv) > 2 else "07055").strip()
    tid, wid = "demo_asin_zip", "wh_nj"
    sku = "S1"

    catalog_body = {
        "sku": sku,
        "asin": asin,
        "weight_lb": 2.0,
        "length_in": 10.0,
        "width_in": 8.0,
        "height_in": 6.0,
    }
    item_intel_request = {
        "warehouses": [
            enrich_warehouse_node_dict(
                {
                    "id": wid,
                    "postal": postal,
                    "target_share_pct": 100,
                    "pricing_profile_id": "profile_nj_v1",
                }
            ),
        ],
        "lanes": [],
        "hub_warehouse_id": wid,
        "preserve_warehouse_target_shares": True,
        "product_origin_postal": postal,
        "include_product_research_economics": False,
    }

    with TestClient(app) as c:
        pr = c.put(f"/v1/operational/{tid}/catalog/items", json=catalog_body)
        if pr.status_code != 200:
            print("catalog PUT failed", pr.status_code, pr.text[:2000])
            sys.exit(1)
        r = c.post(
            f"/v1/operational/{tid}/{wid}/item-intelligence/run",
            json=item_intel_request,
        )
        if r.status_code != 200:
            print("item-intelligence failed", r.status_code, r.text[:4000])
            sys.exit(1)
        j = r.json()

    dem = (j.get("demand_by_sku") or {}).get(sku) or {}
    inv = dem.get("inventory_placement_summary") or {}
    g = j.get("placement_mock_rate_grids") or {}
    alloc = j.get("allocation") or {}
    line = next((ln for ln in (alloc.get("lines") or []) if ln.get("sku") == sku), None)
    wno = j.get("warehouse_network_recommendation_options") or {}
    opts = wno.get("options") or []

    summary = {
        "asin": asin,
        "postal": postal,
        "demand_status": dem.get("status"),
        "monthly_units_est_mid": dem.get("monthly_units_est_mid"),
        "monthly_units_est_low": dem.get("monthly_units_est_low"),
        "monthly_units_est_high": dem.get("monthly_units_est_high"),
        "planning_method": dem.get("planning_method"),
        "keepa_refresh_errors": j.get("keepa_refresh_errors"),
        "inventory_target_days_cover": inv.get("target_days_cover"),
        "inventory_suggested_total_units": inv.get("suggested_total_units_for_target_cover"),
        "placement_grid_status": g.get("status"),
        "mean_mock_parcel_usd_by_warehouse": g.get("mean_mock_parcel_usd_by_warehouse"),
        "allocation_transfer_cost": (line or {}).get("transfer_cost_est_usd"),
        "allocation_placement_headline": (line or {}).get("placement", [])[:3] if line else None,
        "warehouse_network_recommendation_options": [
            {
                "option_key": o.get("option_key"),
                "feasible": o.get("feasible"),
                "selected_warehouse_count": o.get("selected_warehouse_count")
                or o.get("applied_warehouse_count"),
                "hub_warehouse_id": o.get("hub_warehouse_id"),
                "suggested_months_stock_depth_for_hub_spoke_transfer_moq": o.get(
                    "suggested_months_stock_depth_for_hub_spoke_transfer_moq"
                ),
                "achievable_with_deeper_stocking_for_transfer_moq": o.get(
                    "achievable_with_deeper_stocking_for_transfer_moq"
                ),
                "client_planning_nudge": o.get("client_planning_nudge"),
            }
            for o in opts
        ],
        "client_warehouse_network_trim": j.get("client_warehouse_network_trim"),
    }
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()

"""One-off: Product Research Optimization summary for ASIN + origin ZIP (seller-style defaults).

  cd CortexBackend && python3 scripts/run_pro_asin_zip_summary.py B0BZYCJK89 07055
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
    asin = (sys.argv[1] if len(sys.argv) > 1 else "B0BZYCJK89").strip().upper()
    postal = (sys.argv[2] if len(sys.argv) > 2 else "07055").strip()
    tid = "demo_pro_asin_zip"
    wid = "wh-main"
    sku = f"PRO-{asin}"

    warehouses_raw = [
        {"id": "NJ", "postal": "07001", "target_share_pct": 35, "pricing_profile_id": "profile_nj_v1"},
        {"id": "TX", "postal": "75201", "target_share_pct": 30, "pricing_profile_id": "profile_tx_v1"},
        {"id": "FL", "postal": "33101", "target_share_pct": 20, "pricing_profile_id": "profile_fl_v1"},
        {"id": "CA", "postal": "90001", "target_share_pct": 15, "pricing_profile_id": "profile_ca_v1"},
    ]
    lanes = [
        {"from_id": "NJ", "to_id": "TX", "cost_per_lb": 0.07},
        {"from_id": "NJ", "to_id": "FL", "cost_per_lb": 0.06},
        {"from_id": "NJ", "to_id": "CA", "cost_per_lb": 0.09},
    ]
    warehouses = [enrich_warehouse_node_dict(dict(w)) for w in warehouses_raw]

    catalog_body = {
        "sku": sku,
        "asin": asin,
        "weight_lb": 1.5,
        "length_in": 10.0,
        "width_in": 8.0,
        "height_in": 6.0,
        "extra": {"product_origin_postal": postal},
    }

    item_intel_request = {
        "warehouses": warehouses,
        "lanes": lanes,
        "hub_warehouse_id": "NJ",
        "preserve_warehouse_target_shares": True,
        "product_origin_postal": postal,
        "sku_filter": [sku],
        "refresh_keepa": True,
        "include_product_research_economics": True,
        "include_cuopt_tri_modal": False,
        "include_nvidia_cuopt_layer": False,
    }

    with TestClient(app) as c:
        pr = c.put(f"/v1/operational/{tid}/catalog/items", json=catalog_body)
        if pr.status_code != 200:
            print("catalog PUT failed", pr.status_code, pr.text[:4000])
            sys.exit(1)
        r = c.post(
            f"/v1/operational/{tid}/{wid}/product-research-optimization/run",
            json=item_intel_request,
            timeout=600,
        )
        if r.status_code != 200:
            print("PRO run failed", r.status_code, r.text[:8000])
            sys.exit(1)
        j = r.json()

    dem = (j.get("demand_by_sku") or {}).get(sku) or {}
    inv = dem.get("inventory_placement_summary") or {}
    spv = dem.get("seller_planning_velocity") or {}
    pc = j.get("planning_context") or {}
    pmg = j.get("placement_mock_rate_grids") or {}
    mdc = j.get("multi_dc_parallel_scenario") or {}
    tri = j.get("multi_dc_placement_tri_modal") or {}
    pre = j.get("product_research_economics") or {}
    ours = (
        (pre.get("outputs") or {}).get("ours")
        if isinstance(pre.get("outputs"), dict)
        else None
    )
    pr_row = None
    if isinstance(ours, dict):
        for row in ours.get("product_research_by_sku") or []:
            if isinstance(row, dict) and row.get("sku") == sku:
                pr_row = row
                break

    summary = {
        "asin": asin,
        "catalog_sku": sku,
        "product_origin_postal": postal,
        "operational_warehouse_id": wid,
        "demand_by_sku": {
            "status": dem.get("status"),
            "monthly_units_est_mid": dem.get("monthly_units_est_mid"),
            "monthly_units_est_low": dem.get("monthly_units_est_low"),
            "monthly_units_est_high": dem.get("monthly_units_est_high"),
            "planning_method": dem.get("planning_method"),
            "seller_planning_velocity": spv,
            "placement_hints": dem.get("placement_hints"),
        },
        "inventory_placement_summary": {
            "target_days_cover": inv.get("target_days_cover"),
            "suggested_total_units_for_target_cover": inv.get("suggested_total_units_for_target_cover"),
            "monthly_units_est_mid_used": inv.get("monthly_units_est_mid_used"),
            "warehouse_splits": inv.get("warehouse_splits"),
            "network_placement_adjustment": inv.get("network_placement_adjustment"),
            "narrative_bullets": inv.get("narrative_bullets"),
        },
        "planning_context": {
            "planning_velocity_policy": pc.get("planning_velocity_policy"),
            "planning_monthly_units_override_result": pc.get("planning_monthly_units_override_result"),
            "note": pc.get("note"),
        },
        "placement_mock_rate_grids": {
            "status": pmg.get("status"),
            "rate_shopping_execution_summary": pmg.get("rate_shopping_execution_summary"),
        },
        "multi_dc_parallel_scenario": {"status": mdc.get("status"), "reason": mdc.get("reason")},
        "multi_dc_placement_tri_modal": {
            "status": tri.get("status") if isinstance(tri, dict) else None,
            "planning_demand_context": tri.get("planning_demand_context") if isinstance(tri, dict) else None,
        },
        "item_intelligence_synthesis": j.get("item_intelligence_synthesis"),
        "keepa_refresh_errors": j.get("keepa_refresh_errors"),
        "product_research_economics_ours_sku_row": (
            {"sku": pr_row.get("sku"), "scenarios": pr_row.get("scenarios")} if pr_row else None
        ),
    }
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()

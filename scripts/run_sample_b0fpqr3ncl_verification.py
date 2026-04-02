"""Verify Keepa + item intelligence (mock wh_east/wh_west) + label CSV assessment for ASIN B0FPQR3NCL.

Usage (from CortexBackend):
  python scripts/run_sample_b0fpqr3ncl_verification.py
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from unie_cortex.main import app

logging.basicConfig(level=logging.WARNING)
for n in ("sqlalchemy", "sqlalchemy.engine"):
    logging.getLogger(n).setLevel(logging.WARNING)

ASIN = "B0FPQR3NCL"
TENANT = "sample_b0fp"
WID = "wh_east"
SKU = f"DEMO-{ASIN}"


def main() -> None:
    out: dict = {}

    with TestClient(app) as c:
        kr = c.post(
            "/v1/integrations/keepa/product",
            json={"asin": ASIN, "domain": 1, "sku": SKU},
            headers={"X-Unie-Tenant-Id": TENANT},
        )
        kj = kr.json() if kr.headers.get("content-type", "").startswith("application/json") else {}
        out["keepa"] = {
            "http": kr.status_code,
            "ok": kj.get("ok"),
            "error": kj.get("error"),
            "monthly_units_est_mid": (kj.get("demand_extract") or {}).get("monthly_units_est_mid"),
            "planning_method": (kj.get("demand_extract") or {}).get("planning_method"),
        }

        cr = c.put(
            f"/v1/operational/{TENANT}/catalog/items",
            json={"sku": SKU, "asin": ASIN, "weight_lb": 1.2},
        )
        out["catalog_put"] = cr.status_code

        ir = c.post(
            f"/v1/operational/{TENANT}/{WID}/item-intelligence/run",
            json={
                "warehouses": [
                    {"id": WID, "postal": "10001", "target_share_pct": 55},
                    {"id": "wh_west", "postal": "90001", "target_share_pct": 45},
                ],
                "lanes": [{"from_id": WID, "to_id": "wh_west", "cost_per_lb": 0.15}],
                "hub_warehouse_id": WID,
                "preserve_warehouse_target_shares": True,
                "refresh_keepa": False,
            },
        )
        ij = ir.json() if ir.status_code == 200 else {"_error": ir.text[:1200]}
        dem = (ij.get("demand_by_sku") or {}).get(SKU) or {}
        out["item_intelligence"] = {
            "http": ir.status_code,
            "placement_grids": (ij.get("placement_mock_rate_grids") or {}).get("status"),
            "allocation": (ij.get("allocation") or {}).get("status"),
            "demand_status": dem.get("status"),
            "monthly_units_est_mid": dem.get("monthly_units_est_mid"),
            "fully_loaded_usd_per_unit": None,
        }
        for row in (ij.get("landed_cost_economics") or {}).get("per_sku") or []:
            if row.get("sku") == SKU:
                out["item_intelligence"]["fully_loaded_usd_per_unit"] = row.get("fully_loaded_usd_per_unit")
                break

        e = c.post("/v1/assessment/engagements", json={"name": f"sample_csv_{ASIN}"}).json()
        eid = e["engagement_id"]
        c.put(
            f"/v1/assessment/engagements/{eid}/column-mapping",
            json={
                "mappings": {
                    "labels": {
                        "Track": "tracking_number",
                        "Amt": "label_amount_usd",
                        "Wt": "weight_lb",
                        "To": "dest_postal",
                        "Car": "carrier",
                        "Sku": "sku",
                    }
                }
            },
        )
        csv = (
            "Track,Amt,Wt,To,Car,Sku\n"
            f"T-B0FP-1,12.5,1.2,10001,UPS,{SKU}\n"
            f"T-B0FP-2,11.0,1.2,90210,FedEx,{SKU}\n"
        )
        up = c.post(
            f"/v1/assessment/engagements/{eid}/upload?kind=labels",
            files={"file": ("sample_b0fp.csv", csv, "text/csv")},
        )
        out["csv_upload_http"] = up.status_code
        if up.status_code != 200:
            out["csv_upload_detail"] = up.text[:500]
        run = c.post(f"/v1/assessment/engagements/{eid}/runs").json()
        rid = run["run_id"]
        rep = c.get(f"/v1/assessment/engagements/{eid}/runs/{rid}/report").json()
        out["csv_audit"] = {
            "engagement_id": eid,
            "run_id": rid,
            "label_cost_status": (rep.get("label_cost") or {}).get("status"),
            "label_cost_row_count": (rep.get("label_cost") or {}).get("row_count"),
            "throughput_status": (rep.get("throughput") or {}).get("status"),
        }

    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()

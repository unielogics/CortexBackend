#!/usr/bin/env python3
"""Smoke seller optimization pipeline against audit fixtures (truncated for speed)."""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.pop("MONGODB_URI", None)

logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

from fastapi.testclient import TestClient  # noqa: E402
from unie_cortex.main import app  # noqa: E402

FIX = _REPO / "tests" / "fixtures" / "audit"
MAX_DATA_ROWS = 60


def _truncate_csv(raw: bytes, max_rows: int) -> bytes:
    text = raw.decode("utf-8-sig", errors="replace")
    lines = text.splitlines()
    if len(lines) <= 1 or max_rows <= 0:
        return raw
    header, rest = lines[0], lines[1:]
    kept = rest[:max_rows]
    return ("\n".join([header, *kept]) + ("\n" if kept else "")).encode("utf-8")


def main() -> None:
    mapping = json.loads((FIX / "column_mapping.json").read_text(encoding="utf-8"))
    files_spec = [
        ("order_financials", "order_financials.csv"),
        ("order_lines", "order_lines.csv"),
        ("asn", "asn.csv"),
        ("billing", "billing.csv"),
        ("labels", "labels.csv"),
    ]

    with TestClient(app) as c:
        e = c.post("/v1/assessment/engagements", json={"name": "seller-smoke-fixtures"}).json()
        eid = e["engagement_id"]
        assert c.put(
            f"/v1/assessment/engagements/{eid}/column-mapping",
            json={"mappings": mapping},
        ).status_code == 200
        assert c.put(f"/v1/assessment/engagements/{eid}/network-context", json={}).status_code == 200

        for kind, name in files_spec:
            p = FIX / name
            if not p.exists():
                continue
            body = _truncate_csv(p.read_bytes(), MAX_DATA_ROWS)
            r = c.post(
                f"/v1/assessment/engagements/{eid}/upload?kind={kind}",
                files={"file": (name, body, "text/csv")},
            )
            assert r.status_code == 200, (kind, r.text)

        rollup = c.get(f"/v1/assessment/engagements/{eid}/order-financials/sku-rollup").json()
        rows = rollup.get("rows") or []
        origins = {}
        for row in rows[:5]:
            kid = row.get("identifier") or row.get("sku") or row.get("asin")
            if kid:
                origins[str(kid)] = {
                    "source_postal": "07208",
                    "source_city": "Elizabeth",
                    "source_region": "NJ",
                }
        c.put(
            f"/v1/assessment/engagements/{eid}/network-context",
            json={"product_origins_by_sku": origins},
        )

        run = c.post(f"/v1/assessment/engagements/{eid}/runs?with_narrative=false").json()
        rid = run["run_id"]
        report = c.get(f"/v1/assessment/engagements/{eid}/runs/{rid}/report").json()
        syn = c.post(
            f"/v1/assessment/engagements/{eid}/audit-synthesis",
            json={"run_id": rid},
        ).json()
        plan = c.post(
            f"/v1/assessment/engagements/{eid}/order-financials/planning-run",
            json={},
        ).json()

        kpis = syn.get("competitive_kpis") or {}
        hr = syn.get("human_readable") or {}
        fbm = plan.get("scenario_integrated_fbm") or {}
        fba = plan.get("scenario_integrated_fba") or {}

        print("=== Seller optimization local test (tests/fixtures/audit CSVs, truncated) ===")
        print("Engagement:", eid)
        print("CSV cap: first", MAX_DATA_ROWS, "data rows per file")
        print("SKU rollup row_count:", rollup.get("row_count"))
        print("Sample rollup row:", json.dumps(rows[0] if rows else {}, indent=2)[:400])
        print("--- audit-synthesis competitive_kpis ---")
        print("  seller_revenue_usd_total:", kpis.get("seller_revenue_usd_total"))
        print("  seller_net_margin_pct:", kpis.get("seller_net_margin_pct"))
        print("  orders_per_month_estimate:", kpis.get("orders_per_month_estimate"))
        print("  estimated_handle_usd:", kpis.get("estimated_handle_usd"))
        print("  headline:", (hr.get("headline") or "")[:220])
        print("--- spine money_opportunities_usd ---", report.get("money_opportunities_usd"))
        print("--- planning-run ---")
        print("  integrated_rate_shopping_effective:", plan.get("integrated_rate_shopping_effective"))
        print("  scenario_integrated_fbm:", fbm.get("status"), "qty=", fbm.get("qty"))
        if fbm.get("status") == "complete":
            d = fbm.get("direct") or {}
            cons = fbm.get("consolidated") or {}
            print("  FBM direct total_usd:", d.get("total_usd"))
            print("  FBM consolidated total_usd:", cons.get("total_usd"))
        print("  scenario_integrated_fba:", fba.get("status"))


if __name__ == "__main__":
    main()

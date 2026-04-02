#!/usr/bin/env python3
"""
Upload ASN + order_lines + billing fixture CSVs via the in-process assessment API,
then run spine + audit-synthesis (warehouse intelligence + upload opportunities).

Uses the same paths as the portal: POST upload, POST runs, POST audit-synthesis.
Optional: set API_KEY / UNIE_CORTEX_API_KEY if your app enforces auth.

Example:
  python scripts/run_tier1_asn_orders_billing_intelligence.py
  python scripts/run_tier1_asn_orders_billing_intelligence.py --max-rows 120
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path

# Before importing the app: SQLite engine uses echo=True when env is "development".
os.environ["UNIE_CORTEX_ENV"] = "test"
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)

from fastapi.testclient import TestClient

from unie_cortex.main import app
from unie_cortex.spine.fixture_warehouse_baseline import baseline_candidate_warehouses

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures" / "audit"


def _truncate_csv_bytes(raw: bytes, max_rows: int) -> bytes:
    if max_rows <= 0:
        return raw
    text = raw.decode("utf-8-sig", errors="replace")
    lines = text.splitlines()
    if len(lines) <= 1:
        return raw
    header, rest = lines[0], lines[1:]
    kept = rest[:max_rows]
    out = "\n".join([header, *kept]) + ("\n" if kept else "")
    return out.encode("utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--max-rows",
        type=int,
        default=0,
        help="Cap data rows per CSV after header (0 = full fixture files).",
    )
    args = ap.parse_args()
    max_rows = max(0, args.max_rows)

    mapping = json.loads((FIX / "column_mapping.json").read_text(encoding="utf-8"))
    headers: dict[str, str] = {}
    key = os.environ.get("API_KEY") or os.environ.get("UNIE_CORTEX_API_KEY")
    if key:
        headers["X-API-Key"] = key

    asn_b = _truncate_csv_bytes((FIX / "asn.csv").read_bytes(), max_rows)
    ol_b = _truncate_csv_bytes((FIX / "order_lines.csv").read_bytes(), max_rows)
    bl_b = _truncate_csv_bytes((FIX / "billing.csv").read_bytes(), max_rows)

    network_ctx = {
        "candidate_warehouses": baseline_candidate_warehouses(),
        "facility_profile": {
            "sqft": 185000,
            "loading_dock": True,
            "truck_receive_capabilities": "2 dock doors, levelers",
            "headcount_reported": 42,
        },
    }

    with TestClient(app) as client:
        r = client.post("/v1/assessment/engagements", json={"name": "Tier-1 ASN / orders / billing demo"}, headers=headers)
        r.raise_for_status()
        eid = r.json()["engagement_id"]

        r = client.put(
            f"/v1/assessment/engagements/{eid}/column-mapping",
            headers=headers,
            json={"mappings": mapping},
        )
        r.raise_for_status()
        print("column-mapping:", r.json())

        r = client.put(
            f"/v1/assessment/engagements/{eid}/network-context",
            headers=headers,
            json=network_ctx,
        )
        r.raise_for_status()

        for kind, name, body in (
            ("asn", "asn.csv", asn_b),
            ("order_lines", "order_lines.csv", ol_b),
            ("billing", "billing.csv", bl_b),
        ):
            r = client.post(
                f"/v1/assessment/engagements/{eid}/upload?kind={kind}",
                headers=headers,
                files={"file": (name, body, "text/csv")},
            )
            if r.status_code != 200:
                raise SystemExit(f"upload {kind} failed {r.status_code}: {r.text}")
            print(f"upload {kind}:", r.json())

        r = client.post(f"/v1/assessment/engagements/{eid}/runs", headers=headers)
        r.raise_for_status()
        run = r.json()
        print("spine run:", run)

        r = client.post(
            f"/v1/assessment/engagements/{eid}/audit-synthesis",
            headers=headers,
            json={"run_id": run.get("run_id")},
        )
        r.raise_for_status()
        syn = r.json()

    print("\n=== Engagement ===")
    print("engagement_id:", eid)
    if max_rows:
        print(f"(capped each CSV to {max_rows} data rows)")

    cs = syn.get("current_state") or {}
    t1 = cs.get("tier1_row_counts") or {}
    print("\n=== Tier-1 row counts (synthesis) ===")
    print(json.dumps(t1, indent=2))

    wi = cs.get("warehouse_intelligence") or {}
    print("\n=== Warehouse intelligence (subset) ===")
    print(
        json.dumps(
            {
                "estimated_cost_per_fulfillment_usd": wi.get("estimated_cost_per_fulfillment_usd"),
                "billing_usd_total": wi.get("billing_usd_total"),
                "fulfillment_estimate": wi.get("fulfillment_estimate"),
                "capacity_baseline": wi.get("capacity_baseline"),
                "synthetic_fill": wi.get("synthetic_fill"),
            },
            indent=2,
        )
    )

    uo = (syn.get("data_quality") or {}).get("upload_opportunities") or []
    print("\n=== Upload opportunities (first 6) ===")
    for u in uo[:6]:
        print(f"  [{u.get('priority')}] {u.get('title')}")
        if u.get("unlocks"):
            print("      unlocks:", " | ".join(u["unlocks"]))

    th = syn.get("themes") or []
    print("\n=== Themes (first 8) ===")
    for t in th[:8]:
        print(" -", t)

    hr = syn.get("human_readable") or {}
    print("\n=== Human-readable summary ===")
    if hr.get("headline"):
        print(hr["headline"])
    for line in hr.get("summary_lines") or []:
        print(" •", line)
    print("\n--- At a glance ---")
    for card in (hr.get("at_a_glance") or [])[:6]:
        print(f"  * {card.get('title')}: {card.get('body')}")
    if hr.get("warehouse_economics_plain"):
        print("\n--- Warehouse economics (plain) ---")
        print(" ", hr["warehouse_economics_plain"])
    ns = hr.get("next_steps") or []
    if ns:
        print("\n--- Suggested next steps ---")
        for s in ns[:5]:
            print(" ", s)

    print("\n=== Spine summary ===")
    print(json.dumps(syn.get("spine_summary") or {}, indent=2))
    print("\nDone. Full outcome available under POST .../audit-synthesis response.")


if __name__ == "__main__":
    main()

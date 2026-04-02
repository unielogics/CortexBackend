#!/usr/bin/env python3
"""
End-to-end Blitz order-financial flow + network comparison (FBM vs FBA planning modes).

1. Prepare CSV (seller_sku line ids + optional randomized ASIN — demos only; see prepare script)
2. Create engagement → infer mapping → upload order_financials → analyze → audit run
3. Multi-DC preview (heuristic or CUOPT when configured)
4. ``POST .../order-financials/planning-run``: smart network + compare-v2-integrated when
   ``SHIPPO_API_KEY`` is set (parcel rate shopping); otherwise integrated path uses mock parcel legs.
   Linehaul remains mock. Fallback: legacy compare-v2 mock-only calls for the report.

Usage:
  python scripts/run_blitz_full_pipeline.py

Env: set DATABASE_URL before import if you need a file DB; default uses in-memory SQLite
via conftest-style env in this script's __main__ guard.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

# Isolate DB for a clean run unless user exported DATABASE_URL already
if __name__ == "__main__":
    if "DATABASE_URL" not in os.environ:
        os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
    os.environ.pop("MONGODB_URI", None)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _norm_postal(z: str) -> str:
    d = "".join(c for c in str(z or "") if c.isdigit())
    if len(d) >= 5:
        return d[:5]
    if d:
        return d.zfill(5)
    return "10001"


def _prepare_csv(source: Path, output: Path, seed: int) -> None:
    prep = _repo_root() / "scripts" / "prepare_blitz_orders_csv.py"
    subprocess.run(
        [
            sys.executable,
            str(prep),
            "--source",
            str(source),
            "--output",
            str(output),
            "--seed",
            str(seed),
        ],
        check=True,
    )


def _build_destinations_from_csv(text: str, max_qty: int = 2500) -> tuple[int, list[dict]]:
    rows = list(csv.DictReader(io.StringIO(text)))
    qcol = "quantity"
    pcol = "shipTo_postal"
    total_q = 0
    zips: list[str] = []
    for row in rows:
        try:
            q = float(row.get(qcol) or 1)
        except ValueError:
            q = 1.0
        q = max(1.0, q)
        total_q += int(q)
        zp = _norm_postal(row.get(pcol) or "")
        for _ in range(int(q)):
            zips.append(zp)
    scenario_qty = min(max_qty, max(1, int(total_q)))
    # Sample zips weighted by frequency (cap 8 hubs)
    ctr = Counter(zips)
    top = [z for z, _ in ctr.most_common(8)]
    if not top:
        top = ["10001", "75201", "90001", "30309", "07001"]
    n = len(top)
    base = scenario_qty // n
    rem = scenario_qty % n
    dests = []
    for i, postal in enumerate(top):
        u = base + (1 if i < rem else 0)
        if u > 0:
            dests.append({"postal": postal, "units": u})
    s = sum(d["units"] for d in dests)
    if s != scenario_qty and dests:
        dests[-1]["units"] += scenario_qty - s
    return scenario_qty, dests


def main() -> None:
    root = _repo_root()
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--source",
        type=Path,
        default=Path(r"c:\dev\PrepCenterNearMe_system\orders_audit_financials_blitzzecommerce_export.csv"),
    )
    ap.add_argument(
        "--prepared",
        type=Path,
        default=Path(r"c:\dev\PrepCenterNearMe_system\orders_audit_financials_blitzzecommerce_prepared.csv"),
    )
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--skip-prepare", action="store_true")
    ap.add_argument(
        "--report-out",
        type=Path,
        default=root / "blitz_full_pipeline_report.json",
    )
    args = ap.parse_args()

    if not args.skip_prepare:
        if not args.source.is_file():
            raise SystemExit(f"Missing source CSV: {args.source}")
        _prepare_csv(args.source, args.prepared, args.seed)

    if not args.prepared.is_file():
        raise SystemExit(f"Missing prepared CSV: {args.prepared}")

    prepared_text = args.prepared.read_text(encoding="utf-8-sig")
    scenario_qty, destinations = _build_destinations_from_csv(prepared_text)

    from fastapi.testclient import TestClient

    from unie_cortex.config import settings
    from unie_cortex.main import app
    from unie_cortex.services.csv_column_inference import infer_order_financial_mapping

    def _auth_headers() -> dict[str, str]:
        if settings.api_key and str(settings.api_key).strip():
            return {"X-API-Key": str(settings.api_key).strip()}
        if settings.api_keys and str(settings.api_keys).strip():
            first = str(settings.api_keys).split(",")[0].strip()
            if first:
                return {"X-API-Key": first}
        return {}

    buf = io.StringIO(prepared_text)
    headers = list(csv.DictReader(buf).fieldnames or [])
    samples = []
    for i, row in enumerate(csv.DictReader(io.StringIO(prepared_text))):
        samples.append(dict(row))
        if i >= 24:
            break
    inferred = infer_order_financial_mapping(headers, samples)
    mapping_block = {
        "order_financials": dict(inferred["proposed_mapping"]),
        "order_financials_other_expense_headers": [],
    }

    report: dict = {
        "prepared_csv": str(args.prepared.resolve()),
        "scenario_qty": scenario_qty,
        "destination_hubs": destinations,
        "inference": {
            "ambiguous_headers": inferred.get("ambiguous_headers"),
            "unmapped_headers": inferred.get("unmapped_headers"),
        },
    }

    ah = _auth_headers()
    with TestClient(app) as client:
        e = client.post(
            "/v1/assessment/engagements",
            json={"name": "blitz-full-pipeline"},
            headers=ah,
        ).json()
        eid = e["engagement_id"]
        report["engagement_id"] = eid

        mr = client.put(
            f"/v1/assessment/engagements/{eid}/column-mapping",
            json={"mappings": mapping_block},
        )
        report["mapping_save_status"] = mr.status_code
        if mr.status_code != 200:
            report["mapping_save_body"] = mr.text
            args.report_out.write_text(json.dumps(report, indent=2, default=str))
            raise SystemExit("column-mapping failed")

        up = client.post(
            f"/v1/assessment/engagements/{eid}/upload?kind=order_financials",
            files={"file": ("orders_prepared.csv", prepared_text.encode("utf-8"), "text/csv")},
            headers=ah,
        )
        report["upload"] = {"status": up.status_code, "body": up.json() if up.status_code == 200 else up.text}

        an = client.post(
            f"/v1/assessment/engagements/{eid}/order-financials/analyze",
            headers=ah,
        )
        report["order_financial_analyze"] = an.json() if an.status_code == 200 else {"error": an.text}

        pr_plan = client.post(
            f"/v1/assessment/engagements/{eid}/order-financials/planning-run",
            headers=ah,
            json={},
        )
        report["order_financial_planning_run"] = (
            pr_plan.json()
            if pr_plan.status_code == 200
            else {"status": pr_plan.status_code, "error": pr_plan.text}
        )

        run = client.post(f"/v1/assessment/engagements/{eid}/runs", headers=ah)
        report["audit_run"] = run.json() if run.status_code == 200 else {"status": run.status_code, "text": run.text}
        if run.status_code == 200:
            rid = run.json()["run_id"]
            rep = client.get(
                f"/v1/assessment/engagements/{eid}/runs/{rid}/report",
                headers=ah,
            )
            report["audit_report_summary"] = {
                "status": rep.status_code,
                "label_cost_status": (rep.json().get("label_cost") or {}).get("status") if rep.status_code == 200 else None,
            }

        mdc = client.post(
            "/v1/assessment/multi-dc-preview",
            headers=ah,
            json={
                "warehouses": [
                    {"id": "W-CA", "lat": 34.05, "lon": -118.25, "daily_outbound_cuft": 1200},
                    {"id": "W-TX", "lat": 32.78, "lon": -96.80, "daily_outbound_cuft": 900},
                    {"id": "W-NJ", "lat": 40.72, "lon": -74.17, "daily_outbound_cuft": 800},
                ],
                "lanes": [
                    {"from_id": "W-CA", "to_id": "W-TX", "avg_cost_per_cuft": 0.42, "utilization_pct": 55},
                    {"from_id": "W-TX", "to_id": "W-NJ", "avg_cost_per_cuft": 0.38, "utilization_pct": 72},
                    {"from_id": "W-CA", "to_id": "W-NJ", "avg_cost_per_cuft": 0.51, "utilization_pct": 48},
                ],
            },
        )
        report["multi_dc_preview"] = mdc.json() if mdc.status_code == 200 else {"error": mdc.text}

        scenario_base = {
            "weight_lb_per_unit": 1.4,
            "length_in": 9,
            "width_in": 7,
            "height_in": 5,
            "qty": scenario_qty,
            "origins": [
                {"postal": "90001", "warehouse_id": "FBM-WEST"},
                {"postal": "75201", "warehouse_id": "FBM-CENTRAL"},
                {"postal": "07001", "warehouse_id": "FBM-EAST"},
            ],
            "receive_nodes": [
                {"postal": "30309", "warehouse_id": "RCV-ATL"},
                {"postal": "75201", "warehouse_id": "RCV-DAL"},
                {"postal": "07001", "warehouse_id": "RCV-NJ"},
            ],
            "linehaul_origin_postal": "75201",
            "destinations": destinations,
            "carriers": ["usps", "fedex"],
            "freight_mode": "ltl",
            "min_savings_usd": 0,
        }

        pr_raw = report.get("order_financial_planning_run") or {}
        fbm_plan = pr_raw.get("scenario_integrated_fbm") if isinstance(pr_raw, dict) else None
        use_planning = isinstance(fbm_plan, dict) and fbm_plan.get("status") == "complete"
        if not use_planning:
            fbm = client.post(
                "/v1/network/scenarios/compare-v2",
                headers=ah,
                json={**scenario_base, "fulfillment_mode": "fbm"},
            )
            fba = client.post(
                "/v1/network/scenarios/compare-v2",
                headers=ah,
                json={**scenario_base, "fulfillment_mode": "fba"},
            )
            report["network_compare_fbm"] = fbm.json() if fbm.status_code == 200 else {"error": fbm.text}
            report["network_compare_fba"] = fba.json() if fba.status_code == 200 else {"error": fba.text}
        else:
            report["network_compare_fbm"] = {"note": "superseded_by_order_financial_planning_run"}
            report["network_compare_fba"] = {"note": "superseded_by_order_financial_planning_run"}

        ofa = report.get("order_financial_analyze") or {}
        totals = (ofa.get("totals") or {}) if isinstance(ofa, dict) else {}
        pr = report.get("order_financial_planning_run") or {}
        nf = pr.get("scenario_integrated_fbm") or report.get("network_compare_fbm") or {}
        na = pr.get("scenario_integrated_fba") or report.get("network_compare_fba") or {}

        def _net_totals(n: dict) -> dict[str, float | None]:
            if not isinstance(n, dict):
                return {"direct_multi_origin_usd": None, "consolidated_linehaul_plus_parcel_usd": None}
            d = n.get("direct") or {}
            c = n.get("consolidated") or {}
            return {
                "direct_multi_origin_usd": d.get("total_usd"),
                "consolidated_linehaul_plus_parcel_usd": c.get("total_usd"),
            }

        report["interpretation"] = {
            "order_financial_referral_modeled_usd": totals.get("referral_fees_modeled_usd"),
            "order_financial_implied_amazon_non_referral_usd": totals.get("implied_non_referral_marketplace_usd"),
            "integrated_rate_shopping_effective": pr.get("integrated_rate_shopping_effective"),
            "fulfillment_comparison_fbm": pr.get("fulfillment_comparison_fbm"),
            "fulfillment_comparison_fba": pr.get("fulfillment_comparison_fba"),
            "note": (
                "CSV marketplace_fees mixes referral + Amazon fulfillment; modeled referral is the referral slice. "
                "implied_non_referral is marketplace_fees minus modeled referral (rough FBA/fulfillment-heavy slice). "
                "planning-run uses smart-network topology from order ZIPs; parcel legs use integrated rate shopping "
                "when SHIPPO_API_KEY is configured, else mock zones. Linehaul is still mock LTL/FTL."
            ),
            "network_scenario_usd": {
                "fulfillment_mode_fbm": _net_totals(nf),
                "fulfillment_mode_fba": _net_totals(na),
            },
        }

    args.report_out.write_text(json.dumps(report, indent=2, default=str))
    print(f"Wrote {args.report_out.resolve()}")


if __name__ == "__main__":
    main()

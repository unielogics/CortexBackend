#!/usr/bin/env python3
"""
Ingest an order-financial CSV (in-memory DB), run referral + fee pipeline, print analysis.

Usage:
  python scripts/run_order_financial_analysis.py [path/to/orders.csv]
  python scripts/run_order_financial_analysis.py path/to/orders.csv --planning

``--planning`` adds smart-network recommendation, compare-v2-integrated (rate shopping when
``SHIPPO_API_KEY`` is set), and ``fulfillment_comparison`` for FBM and FBA — same ideas as
``POST .../order-financials/planning-run``.

If no path is given, uses tests/fixtures/order_financial_sample.csv.

Set DATABASE_URL / MONGODB_URI in the environment before running if you want a persistent DB;
otherwise this script forces in-memory SQLite for an isolated demo.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import io
import json
import os
import sys
import uuid
from pathlib import Path

# Must run before any unie_cortex import (Settings loads .env once).
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.pop("MONGODB_URI", None)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _default_csv() -> Path:
    return _repo_root() / "tests" / "fixtures" / "order_financial_sample.csv"


async def _main(
    csv_path: Path, *, with_planning: bool = False, csv_baseline_fulfillment: str | None = None
) -> None:
    from unie_cortex.config import settings
    from unie_cortex.product_identity import seller_optimization_engine_identity
    from unie_cortex.db.database import SessionLocal, init_sql_db
    from unie_cortex.db.store import SqlCortexStore
    from unie_cortex.services.csv_column_inference import infer_order_financial_mapping
    from unie_cortex.services.order_financial_analysis import analyze_order_financial_facts
    from unie_cortex.network.scenario_vocabulary import (
        csv_baseline_comparison_title,
        normalize_csv_baseline_fulfillment,
    )
    from unie_cortex.services.order_financial_planning import (
        build_fulfillment_comparison,
        build_order_financial_planning_four_views,
        build_planning_comparison_matrix_v1,
        compute_fba_inbound_for_planning,
        integrated_rate_shopping_effective,
        run_integrated_compare_for_order_planning,
    )
    from unie_cortex.spine.order_financial_ingest import ingest_order_financials_csv

    text = csv_path.read_text(encoding="utf-8-sig")
    headers = list(csv.DictReader(io.StringIO(text)).fieldnames or [])
    sample_rows: list[dict] = []
    for i, row in enumerate(csv.DictReader(io.StringIO(text))):
        sample_rows.append(dict(row))
        if i >= 19:
            break

    inferred = infer_order_financial_mapping(headers, sample_rows)
    proposed = inferred["proposed_mapping"]

    await init_sql_db()
    assert SessionLocal is not None

    eid = str(uuid.uuid4())
    mapping_doc = {
        "order_financials": {k: v for k, v in proposed.items() if v},
        "order_financials_other_expense_headers": inferred.get("other_expense_column_candidates") or [],
    }

    async with SessionLocal() as session:
        store = SqlCortexStore(session)
        await store.engagement_create(eid, f"order-financial-demo-{eid[:8]}", None, None)
        await store.mapping_save(eid, mapping_doc)
        batch_id, n = await ingest_order_financials_csv(
            store,
            eid,
            text.encode("utf-8"),
            csv_path.name,
            mapping_doc,
        )
        rows = await store.order_financial_facts_list(engagement_id=eid)
        await session.commit()

    analysis = analyze_order_financial_facts(rows)
    img = analysis.get("full_financial_image") or {}
    totals = analysis.get("totals") or {}
    out_audit = {
        "referral_fees_modeled_usd": totals.get("referral_fees_modeled_usd"),
        "fba_fulfillment_fee_audit_line_total_usd": totals.get("fba_fulfillment_fee_audit_line_total_usd"),
        "audit_legend": img.get("amazon_fee_audit_legend"),
        "settings_echo": {
            "amazon_fee_audit_grade": settings.amazon_fee_audit_grade,
            "amazon_referral_minimum_usd_per_item": settings.amazon_referral_minimum_usd_per_item,
            "amazon_fba_audit_enabled": settings.amazon_fba_audit_enabled,
            "amazon_fba_audit_default_shipping_weight_lb": settings.amazon_fba_audit_default_shipping_weight_lb,
            "amazon_fba_audit_default_size_tier": settings.amazon_fba_audit_default_size_tier,
        },
    }

    def _total_units(rs: list) -> int:
        s = 0.0
        for r in rs:
            try:
                q = float(r.get("quantity") or 0)
            except (TypeError, ValueError):
                q = 1.0
            s += max(1.0, q)
        return max(1, int(s))

    out: dict = {
        "seller_optimization_engine": seller_optimization_engine_identity(),
        "csv_file": str(csv_path.resolve()),
        "engagement_id": eid,
        "batch_id": batch_id,
        "rows_ingested": n,
        "inferred_mapping": proposed,
        "inference_notes": {
            "unmapped_headers": inferred.get("unmapped_headers"),
            "ambiguous_headers": inferred.get("ambiguous_headers"),
            "other_expense_column_candidates": inferred.get("other_expense_column_candidates"),
        },
        "analysis": analysis,
        "amazon_fee_audit_summary": out_audit,
        "sample_facts": rows[: min(5, len(rows))],
    }

    if with_planning:
        scenario_cap = min(2500, _total_units(rows))
        csv_base = normalize_csv_baseline_fulfillment(csv_baseline_fulfillment)
        out["integrated_rate_shopping_effective"] = integrated_rate_shopping_effective(settings)
        out["csv_baseline_fulfillment"] = csv_base
        out["csv_baseline_comparison_title"] = csv_baseline_comparison_title(csv_base)
        planning: dict = {}
        for mode in ("fbm", "fba"):
            scen = await run_integrated_compare_for_order_planning(
                rows=rows,
                cfg=settings,
                fulfillment_mode=mode,
                max_scenario_qty=scenario_cap,
                analysis=analysis,
            )
            if scen.get("status") == "complete":
                v = dict(scen.get("vocabulary") or {})
                v["csv_baseline_fulfillment"] = csv_base
                v["csv_baseline_comparison_title"] = csv_baseline_comparison_title(csv_base)
                scen["vocabulary"] = v
            planning[f"scenario_integrated_{mode}"] = scen
            planning[f"fulfillment_comparison_{mode}"] = build_fulfillment_comparison(
                analysis=analysis,
                integrated_scenario=scen if scen.get("status") == "complete" else None,
                scenario_qty=scen.get("qty"),
                fulfillment_mode=mode,
                csv_baseline_fulfillment=csv_base,
            )
        fba_inbound_fin = None
        scen_fba = planning.get("scenario_integrated_fba")
        if isinstance(scen_fba, dict) and scen_fba.get("status") == "complete":
            fba_inbound_fin = await compute_fba_inbound_for_planning(
                scenario_fba=scen_fba,
                analysis=analysis,
                inbound_from_supplier=None,
                fba_prep_line_items=None,
                qualifying_order_value_usd=None,
                weight_lb_per_unit=1.4,
                length_in=9.0,
                width_in=7.0,
                height_in=5.0,
                use_integrated_parcel=True,
                cfg=settings,
            )
            if fba_inbound_fin:
                scen_fba["fba_inbound_economics"] = fba_inbound_fin
            planning["fulfillment_comparison_fba"] = build_fulfillment_comparison(
                analysis=analysis,
                integrated_scenario=scen_fba,
                scenario_qty=scen_fba.get("qty"),
                fulfillment_mode="fba",
                csv_baseline_fulfillment=csv_base,
            )
        out["planning_run"] = planning
        out["planning_comparison_matrix"] = build_planning_comparison_matrix_v1(
            analysis=analysis,
            scenario_fbm=planning.get("scenario_integrated_fbm"),
            scenario_fba=planning.get("scenario_integrated_fba"),
            fba_inbound_economics=fba_inbound_fin,
            csv_baseline_fulfillment=csv_base,
        )
        out["planning_four_views"] = build_order_financial_planning_four_views(
            analysis=analysis,
            scenario_fbm=planning.get("scenario_integrated_fbm"),
            scenario_fba=planning.get("scenario_integrated_fba"),
            csv_baseline_fulfillment=csv_base,
        )

    print(json.dumps(out, indent=2, default=str))


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingest order-financial CSV and print analysis JSON.")
    ap.add_argument(
        "csv_path",
        nargs="?",
        default=None,
        help="Path to CSV (default: tests/fixtures/order_financial_sample.csv)",
    )
    ap.add_argument(
        "--planning",
        action="store_true",
        help="Run warehouse network + integrated scenario + fulfillment_comparison (FBM/FBA)",
    )
    ap.add_argument(
        "--csv-baseline",
        choices=("fba", "fbw", "fbm"),
        default=None,
        help="Current fulfillment label for comparison titles: Current (FBA|FBW|FBM). Default: fba.",
    )
    args = ap.parse_args()
    p = Path(args.csv_path).expanduser() if args.csv_path else _default_csv()
    if not p.is_file():
        print(f"File not found: {p}", file=sys.stderr)
        sys.exit(1)
    asyncio.run(_main(p, with_planning=args.planning, csv_baseline_fulfillment=args.csv_baseline))


if __name__ == "__main__":
    main()

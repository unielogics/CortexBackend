#!/usr/bin/env python3
"""
Sum order-financial CSV columns (Amazon-side fee view) and run integrated scenarios:

- FBA guidance: transport stack only (``fulfillment_mode=fba``; marketplace fees stay in CSV).
- FBM multi-hub: cheapest ship-from per destination over **all** recommended warehouse origins.
- FBM single-hub: only the **hub** origin and matching receive node (all parcel from one node;
  consolidated linehaul still from hub postal).

When the smart network recommends a single node, multi-hub and single-hub FBM totals are identical.

Usage:
  python scripts/run_order_financial_fbm_csv_rollups.py [path/to.csv]
  python scripts/run_order_financial_fbm_csv_rollups.py   # tests/fixtures/order_financial_sample.csv
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
from typing import Any

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.pop("MONGODB_URI", None)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _default_csv() -> Path:
    return _repo_root() / "tests" / "fixtures" / "order_financial_sample.csv"


def _float(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def csv_column_rollups(raw_text: str, *, header_to_field: dict[str, str]) -> dict[str, Any]:
    """Sum numeric columns using original CSV headers (before canonical mapping)."""
    rev_h = {v: k for k, v in header_to_field.items() if v}
    r_rev = rev_h.get("revenue_usd", "revenue")
    r_mf = rev_h.get("marketplace_fees_usd", "marketplace_fees")
    r_tf = rev_h.get("total_fees_usd", "total_fees")
    r_pf = rev_h.get("profit_usd", "profit")
    r_prep = rev_h.get("prep_cost_usd", "prep_cost")
    r_inb = rev_h.get("inbound_cost_usd", "inbound_cost")
    r_qty = rev_h.get("quantity", "quantity")

    out = {
        "row_count": 0,
        "quantity_units": 0.0,
        "revenue_usd": 0.0,
        "marketplace_fees_usd": 0.0,
        "total_fees_usd": 0.0,
        "profit_usd": 0.0,
        "prep_cost_usd": 0.0,
        "inbound_cost_usd": 0.0,
    }
    for row in csv.DictReader(io.StringIO(raw_text)):
        out["row_count"] += 1
        q = max(1.0, _float(row.get(r_qty), 1.0))
        out["quantity_units"] += q
        out["revenue_usd"] += _float(row.get(r_rev))
        out["marketplace_fees_usd"] += _float(row.get(r_mf))
        out["total_fees_usd"] += _float(row.get(r_tf))
        out["profit_usd"] += _float(row.get(r_pf))
        out["prep_cost_usd"] += _float(row.get(r_prep))
        out["inbound_cost_usd"] += _float(row.get(r_inb))
    for k in list(out.keys()):
        if k != "row_count" and isinstance(out[k], float):
            out[k] = round(out[k], 2)
    return out


def _pct_diff(a: float, b: float) -> dict[str, float | None]:
    """Return (b - a) / a and (a - b) / b as percentages when denominators nonzero."""
    out: dict[str, float | None] = {
        "delta_b_minus_a_usd": round(b - a, 2) if a or b else None,
        "pct_higher_vs_a": round(100.0 * (b - a) / a, 2) if a else None,
        "pct_lower_than_b": round(100.0 * (a - b) / b, 2) if b else None,
    }
    return out


def _pick_scenario_transport_and_allin(sc: dict[str, Any]) -> dict[str, Any]:
    d, c = sc.get("direct") or {}, sc.get("consolidated") or {}
    return {
        "direct_all_in_usd": float(d.get("total_usd") or 0),
        "consolidated_all_in_usd": float(c.get("total_usd") or 0),
        "direct_transport_usd": float(d.get("transport_parcel_total_usd") or 0),
        "consolidated_transport_usd": float(c.get("transport_linehaul_plus_parcel_total_usd") or 0),
        "qty": sc.get("qty"),
        "status": sc.get("status"),
    }


async def _main(csv_path: Path) -> dict[str, Any]:
    from unie_cortex.config import settings
    from unie_cortex.db.database import SessionLocal, init_sql_db
    from unie_cortex.db.store import SqlCortexStore
    from unie_cortex.network.scenarios_integrated import compare_scenario_v2_integrated
    from unie_cortex.services.csv_column_inference import infer_order_financial_mapping
    from unie_cortex.services.order_financial_analysis import analyze_order_financial_facts
    from unie_cortex.services.order_financial_planning import (
        destinations_from_order_rows_weighted_zip5,
        integrated_rate_shopping_effective,
        recommend_warehouse_network_for_order_financial_rows,
        scenario_payload_from_network_recommendation,
    )
    from unie_cortex.spine.order_financial_ingest import ingest_order_financials_csv

    text = csv_path.read_text(encoding="utf-8-sig")
    headers = list(csv.DictReader(io.StringIO(text)).fieldnames or [])
    sample_rows = [dict(r) for i, r in enumerate(csv.DictReader(io.StringIO(text))) if i < 20]
    inferred = infer_order_financial_mapping(headers, sample_rows)
    proposed = inferred["proposed_mapping"]
    mapping_doc = {
        "order_financials": {k: v for k, v in proposed.items() if v},
        "order_financials_other_expense_headers": inferred.get("other_expense_column_candidates") or [],
    }

    csv_rollup = csv_column_rollups(text, header_to_field=proposed)

    await init_sql_db()
    assert SessionLocal is not None
    eid = str(uuid.uuid4())
    async with SessionLocal() as session:
        store = SqlCortexStore(session)
        await store.engagement_create(eid, f"fbm-csv-rollup-{eid[:8]}", None, None)
        await store.mapping_save(eid, mapping_doc)
        await ingest_order_financials_csv(
            store, eid, text.encode("utf-8"), csv_path.name, mapping_doc
        )
        rows = await store.order_financial_facts_list(engagement_id=eid)
        await session.commit()

    analysis = analyze_order_financial_facts(rows)
    totals = analysis.get("totals") or {}

    weight_lb = 1.4
    net = recommend_warehouse_network_for_order_financial_rows(rows, settings, default_weight_lb=weight_lb)
    qty, dests = destinations_from_order_rows_weighted_zip5(rows, max_qty=2500)
    base = scenario_payload_from_network_recommendation(
        net,
        destinations=dests,
        qty=qty,
        weight_lb_per_unit=weight_lb,
        length_in=9.0,
        width_in=7.0,
        height_in=5.0,
    )
    if not base:
        return {
            "csv_file": str(csv_path.resolve()),
            "csv_column_rollups_fba_export_columns": csv_rollup,
            "status": "skipped",
            "message": "warehouse recommendation produced no nodes",
            "warehouse_network": net,
        }

    use_int = integrated_rate_shopping_effective(settings)
    lh_mult = float(getattr(settings, "network_consolidated_linehaul_cost_multiplier", 1.0) or 1.0)

    async def _run(origins: list[dict], receive_nodes: list[dict], fm: str) -> dict[str, Any]:
        return await compare_scenario_v2_integrated(
            weight_lb_per_unit=base["weight_lb_per_unit"],
            length_in=base["length_in"],
            width_in=base["width_in"],
            height_in=base["height_in"],
            qty=base["qty"],
            origins=origins,
            receive_nodes=receive_nodes,
            linehaul_origin_postal=base["linehaul_origin_postal"],
            destinations=base["destinations"],
            carriers_fallback=list(base["carriers"]),
            min_savings_usd=base["min_savings_usd"],
            freight_mode=base["freight_mode"],
            direct_use_integrated=use_int,
            consolidated_parcel_use_integrated=use_int,
            fulfillment_mode=fm,
            consolidated_linehaul_cost_multiplier=lh_mult,
        )

    hub_id = str(net.get("hub_warehouse_id") or base["origins"][0]["warehouse_id"])
    hub_origin = next((o for o in base["origins"] if o["warehouse_id"] == hub_id), base["origins"][0])
    hub_receive = next(
        (r for r in base["receive_nodes"] if str(r.get("warehouse_id") or "") == f"RCV-{hub_id}"),
        base["receive_nodes"][0],
    )

    multi_fbm = await _run(base["origins"], base["receive_nodes"], "fbm")
    single_fbm = await _run([hub_origin], [hub_receive], "fbm")
    multi_fba = await _run(base["origins"], base["receive_nodes"], "fba")

    mf_m = _pick_scenario_transport_and_allin(multi_fbm)
    mf_s = _pick_scenario_transport_and_allin(single_fbm)
    fa_m = _pick_scenario_transport_and_allin(multi_fba)

    n_nodes = len(base["origins"])
    same_topology = n_nodes <= 1 or (
        mf_m["direct_all_in_usd"] == mf_s["direct_all_in_usd"]
        and mf_m["consolidated_all_in_usd"] == mf_s["consolidated_all_in_usd"]
    )

    rev = float(csv_rollup.get("revenue_usd") or 0)
    mf_csv = float(csv_rollup.get("marketplace_fees_usd") or 0)

    return {
        "csv_file": str(csv_path.resolve()),
        "csv_column_rollups_fba_export_columns": csv_rollup,
        "csv_derived_ratios": {
            "marketplace_fees_pct_of_revenue": round(100.0 * mf_csv / rev, 2) if rev else None,
            "total_fees_pct_of_revenue": round(
                100.0 * float(csv_rollup.get("total_fees_usd") or 0) / rev, 2
            )
            if rev
            else None,
        },
        "analysis_totals_same_ingested_rows": {
            k: totals.get(k)
            for k in (
                "revenue_usd",
                "marketplace_fees_usd",
                "referral_fees_modeled_usd",
                "implied_non_referral_marketplace_usd",
                "total_fees_usd",
                "profit_usd",
                "prep_cost_usd",
                "inbound_cost_usd",
            )
        },
        "scenario_bases": {
            "scenario_qty": qty,
            "destination_buckets": len(dests),
            "recommended_warehouse_count": n_nodes,
            "hub_warehouse_id": hub_id,
            "note_if_single_node_multi_equals_single_fbm": (
                "Network recommended only one ship node; multi-hub and single-hub FBM paths coincide."
                if n_nodes <= 1
                else None
            ),
        },
        "fba_guidance_transport_only_multi_origin_topology": fa_m,
        "fbm_multi_hub_cheapest_origin_per_destination": mf_m,
        "fbm_single_hub_ship_and_receive_at_hub_only": mf_s,
        "fbm_multi_vs_single_direct_all_in": _pct_diff(mf_s["direct_all_in_usd"], mf_m["direct_all_in_usd"]),
        "fbm_multi_direct_vs_consolidated_all_in": _pct_diff(
            mf_m["direct_all_in_usd"], mf_m["consolidated_all_in_usd"]
        ),
        "same_multi_and_single_fbm_totals": same_topology,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="CSV rollups + FBM multi/single hub scenario totals.")
    ap.add_argument(
        "csv_path",
        nargs="?",
        default=None,
        help="Path to CSV (default: tests/fixtures/order_financial_sample.csv)",
    )
    args = ap.parse_args()
    p = Path(args.csv_path).expanduser() if args.csv_path else _default_csv()
    if not p.is_file():
        print(f"File not found: {p}", file=sys.stderr)
        sys.exit(1)
    out = asyncio.run(_main(p))
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Load tests/fixtures/audit CSVs into a temp SQLite DB and print spine + audit outcome summary.

Deterministic audit (default): backbone_completeness, competitive_kpis, and strategy suggestions need no GPU or LLM.

Optional NIM layer: pass ``--with-ai-recommendations`` (requires ``NVIDIA_API_KEY``, optional ``NIM_BASE_URL`` /
``NIM_MODEL``) to call the same ``chat/completions`` path as ``POST .../audit-synthesis`` with
``with_ai_recommendations: true``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path

# Allow `python scripts/run_audit_mock_fixtures_demo.py` from repo root (Windows/Linux).
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from unie_cortex.db import models as db_models
from unie_cortex.db.store import SqlCortexStore
from unie_cortex.services.audit_backbone import build_backbone_completeness
from unie_cortex.services.audit_grain import build_grain_report
from unie_cortex.services.audit_synthesis import build_audit_outcome, load_audit_benchmark_profile
from unie_cortex.services.order_financial_analysis import analyze_order_financial_facts
from unie_cortex.integrations.rate_shopping import RateShoppingService
from unie_cortex.services.complementary_network_audit import build_complementary_network_audit
from unie_cortex.services.audit_sharpness_metrics import build_audit_sharpness_metrics
from unie_cortex.services.label_network_insights import build_label_network_insights
from unie_cortex.services.warehouse_competitive_kpis import build_competitive_kpis
from unie_cortex.spine.ingest import ingest_labels_csv
from unie_cortex.spine.order_financial_ingest import ingest_order_financials_csv
from unie_cortex.spine.runner import parse_mapping_payload, parse_tier1_mapping_blocks, run_audit_spine
from unie_cortex.spine.tier1_ingest import (
    ingest_asn_csv,
    ingest_billing_lines_csv,
    ingest_employees_csv,
    ingest_order_lines_csv,
)
from unie_cortex.spine.fixture_warehouse_baseline import (
    AUDIT_BASELINE_ADDRESS_LINE,
    baseline_candidate_warehouses,
)
from unie_cortex.services.synthetic_tasks import ensure_synthetic_tasks_from_tier1
from unie_cortex.services.warehouse_intelligence_baseline import build_warehouse_intelligence_baseline
from unie_cortex.services.warehouse_strategy_suggestions import build_warehouse_strategy_suggestions
from unie_cortex.config import settings
from unie_cortex.services.nim_warehouse_audit import build_nim_audit_payload, generate_audit_ai_recommendations
from unie_cortex.spine.mock_audit_enrichment import (
    inject_fbm_pick_pack_billing_rows,
    summarize_mock_pipeline_checks,
)

ROOT = _REPO_ROOT
FIX = ROOT / "tests" / "fixtures" / "audit"


def _truncate_csv_bytes(raw: bytes, max_rows: int) -> bytes:
    """Keep header + first max_rows data rows (UTF-8 CSV)."""
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


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--max-rows",
        type=int,
        default=80,
        help="Cap rows per CSV after header (0 = use full files; order ingest is slow on 500 rows).",
    )
    ap.add_argument(
        "--inject-handles",
        type=int,
        default=50,
        help="Append N mock FBM_PICK_PACK lines (~$2.50–$3.50) to billing so variable handle math shows up (0=off).",
    )
    ap.add_argument(
        "--verbose",
        action="store_true",
        help="Print full warehouse_intelligence JSON (default: summary + human-readable only).",
    )
    ap.add_argument(
        "--with-ai-recommendations",
        action="store_true",
        help="After deterministic outcome, call NVIDIA NIM chat/completions (needs NVIDIA_API_KEY).",
    )
    ap.add_argument(
        "--ai-detail",
        choices=("brief", "full"),
        default="brief",
        help="Payload size for NIM (only with --with-ai-recommendations).",
    )
    args = ap.parse_args()
    max_rows = max(0, args.max_rows)

    mapping = json.loads((FIX / "column_mapping.json").read_text(encoding="utf-8"))
    ml, mt = parse_mapping_payload(mapping)
    # Typical customer: no tasks CSV — spine still receives mapping tasks for coverage; tasks come from synthesis.
    m_asn, m_ol, m_bl, m_emp = parse_tier1_mapping_blocks(mapping)

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    path = tmp.name
    engine = None
    try:
        if max_rows:
            print(f"(Using first {max_rows} data rows per CSV for speed; pass --max-rows 0 for full files.)\n")
        if args.inject_handles > 0:
            print(
                f"(Injecting {args.inject_handles} mock FBM_PICK_PACK billing lines for realistic ~$3 handles; "
                "use --inject-handles 0 to use raw billing fixture only.)\n"
            )
        print(f"Warehouse baseline (origin): {AUDIT_BASELINE_ADDRESS_LINE}\n")
        engine = create_async_engine(f"sqlite+aiosqlite:///{path}", echo=False, poolclass=NullPool)
        async with engine.begin() as conn:
            await conn.run_sync(db_models.Base.metadata.create_all)
        SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with SessionLocal() as session:
            store = SqlCortexStore(session)
            eid = "demo-fixtures-engagement"
            await store.engagement_create(eid, "Mock fixtures demo", None, None)
            await store.mapping_save(eid, mapping)
            await store.engagement_set_network_context(
                eid,
                {
                    "candidate_warehouses": baseline_candidate_warehouses(),
                    "facility_profile": {
                        "sqft": 185000,
                        "loading_dock": True,
                        "truck_receive_capabilities": "2 dock doors with levelers; 53 ft trailers by appointment; no rail.",
                        "headcount_reported": 42,
                    },
                },
            )
            eng = await store.engagement_get(eid)
            nc = (eng or {}).get("network_context") or {}
            wh_candidates = (
                nc.get("candidate_warehouses") if isinstance(nc.get("candidate_warehouses"), list) else None
            )

            lb = _truncate_csv_bytes((FIX / "labels.csv").read_bytes(), max_rows)
            ob = _truncate_csv_bytes((FIX / "order_financials.csv").read_bytes(), max_rows)
            ab = _truncate_csv_bytes((FIX / "asn.csv").read_bytes(), max_rows)
            olb = _truncate_csv_bytes((FIX / "order_lines.csv").read_bytes(), max_rows)
            bb = _truncate_csv_bytes((FIX / "billing.csv").read_bytes(), max_rows)
            if args.inject_handles > 0:
                bb = inject_fbm_pick_pack_billing_rows(bb, args.inject_handles)
            eb = _truncate_csv_bytes((FIX / "employees.csv").read_bytes(), max_rows)

            await ingest_labels_csv(
                store, eid, lb, "labels.csv", ml, candidate_warehouses=wh_candidates
            )
            await ingest_order_financials_csv(store, eid, ob, "order_financials.csv", mapping)
            await ingest_asn_csv(store, eid, ab, "asn.csv", m_asn)
            await ingest_order_lines_csv(store, eid, olb, "order_lines.csv", m_ol)
            await ingest_billing_lines_csv(store, eid, bb, "billing.csv", m_bl)
            await ingest_employees_csv(store, eid, eb, "employees.csv", m_emp)

            syn = await ensure_synthetic_tasks_from_tier1(store, eid)
            artifact = await run_audit_spine(store, ml, mt, engagement_id=eid, mode="assessment")

            labels = await store.label_facts_list(engagement_id=eid)
            tasks = await store.task_facts_list(engagement_id=eid)
            of_rows = await store.order_financial_facts_list(engagement_id=eid)
            asn_rows = await store.asn_facts_list(eid)
            ol_rows = await store.order_line_facts_list(eid)
            bl_rows = await store.billing_line_facts_list(eid)
            emp_rows = await store.employee_facts_list(eid)

            grain = build_grain_report(
                eid,
                labels,
                tasks,
                of_rows,
                asn_rows=asn_rows,
                order_line_rows=ol_rows,
                billing_rows=bl_rows,
                employee_rows=emp_rows,
            )
            order_analysis = analyze_order_financial_facts(of_rows) if of_rows else None
            eng_doc = await store.engagement_get(eid)
            nc_full = (eng_doc or {}).get("network_context") or {}
            nc_full = nc_full if isinstance(nc_full, dict) else {}
            fp = nc_full.get("facility_profile")
            fp = fp if isinstance(fp, dict) else {}
            wh_intel = build_warehouse_intelligence_baseline(
                facility_profile=fp,
                labels=labels,
                tasks=tasks,
                asn_rows=asn_rows,
                order_lines=ol_rows,
                billing_rows=bl_rows,
                employee_rows=emp_rows,
                network_context=nc_full,
            )
            backbone = build_backbone_completeness(grain=grain, facility_profile=fp, network_context=nc_full)
            competitive_kpis = build_competitive_kpis(
                grain=grain,
                warehouse_intelligence=wh_intel,
                order_analysis=order_analysis,
            )
            wh_intel["label_network_insights"] = build_label_network_insights(
                labels=labels,
                network_context=nc_full,
                label_cost_module=artifact.get("label_cost") if isinstance(artifact.get("label_cost"), dict) else None,
                money_opportunities_usd=artifact.get("money_opportunities_usd")
                if isinstance(artifact.get("money_opportunities_usd"), dict)
                else None,
            )
            wh_intel["complementary_network_audit"] = await build_complementary_network_audit(
                store=store,
                tenant_id=eid,
                labels=labels,
                order_lines=ol_rows,
                network_context=nc_full,
                rss=RateShoppingService(),
                use_cache=True,
            )
            wh_intel["audit_sharpness_metrics"] = build_audit_sharpness_metrics(
                labels=labels,
                tasks=tasks,
                order_lines=ol_rows,
                billing_rows=bl_rows,
                order_financials=of_rows,
                asn_rows=asn_rows,
                employee_rows=emp_rows,
                grain=grain,
                warehouse_intelligence=wh_intel,
                competitive_kpis=competitive_kpis,
                order_analysis=order_analysis,
                backbone_completeness=backbone,
            )
            wh_intel["strategy_suggestions"] = build_warehouse_strategy_suggestions(
                warehouse_intelligence=wh_intel,
                order_lines=ol_rows,
                labels=labels,
                network_context=nc_full,
                grain=grain,
                competitive_kpis=competitive_kpis,
                label_network_insights=wh_intel.get("label_network_insights"),
            )
            outcome = build_audit_outcome(
                engagement_id=eid,
                spine_artifact=artifact,
                grain=grain,
                benchmark=load_audit_benchmark_profile(None),
                order_analysis=order_analysis,
                run_id=None,
                warehouse_intelligence=wh_intel,
                facility_profile=fp,
                network_context=nc_full,
                backbone_completeness=backbone,
                competitive_kpis=competitive_kpis,
            )

            await session.commit()

        od_full = outcome.model_dump()

        print("=== Ingest row counts (facts inserted) ===")
        print(
            json.dumps(
                {
                    "labels": len(labels),
                    "tasks": len(tasks),
                    "order_financials": len(of_rows),
                    "asn": len(asn_rows),
                    "order_lines": len(ol_rows),
                    "billing": len(bl_rows),
                    "employees": len(emp_rows),
                },
                indent=2,
            )
        )
        print("\n=== Synthetic tasks (no tasks CSV — from ASN + order_lines) ===")
        print(json.dumps(syn, indent=2))
        od_full = outcome.model_dump()
        checks = summarize_mock_pipeline_checks(wh_intel, od_full)
        print("\n=== Mock pipeline checks (read this first) ===")
        print(json.dumps(checks, indent=2))

        print("\n=== Human-readable summary (same shape as POST .../audit-synthesis) ===")
        hr = od_full.get("human_readable") or {}
        print(hr.get("headline", ""))
        for line in hr.get("summary_lines") or []:
            print(" •", line)
        print("\n--- At a glance (first 5) ---")
        for card in (hr.get("at_a_glance") or [])[:5]:
            print(f"  * {card.get('title')}: {card.get('body')}")
        print("\n--- Warehouse strategy suggestions (titles) ---")
        for s in hr.get("warehouse_strategy_suggestions") or []:
            print(f"  - [{s.get('priority')}/{s.get('category')}] {s.get('title')}")

        print("\n=== Warehouse intelligence baseline (facility profile + billing + activity) ===")
        if args.verbose:
            print(json.dumps(wh_intel, indent=2))
        else:
            print(
                json.dumps(
                    {
                        "schema_version": wh_intel.get("schema_version"),
                        "location_context": wh_intel.get("location_context"),
                        "billing_components_usd": wh_intel.get("billing_components_usd"),
                        "fulfillment_economics": wh_intel.get("fulfillment_economics"),
                        "volume_baseline": wh_intel.get("volume_baseline"),
                        "labor_baseline": wh_intel.get("labor_baseline"),
                        "strategy_suggestions_count": len(wh_intel.get("strategy_suggestions") or []),
                        "synthetic_fill": wh_intel.get("synthetic_fill"),
                    },
                    indent=2,
                )
            )
            print("(Use --verbose for full warehouse_intelligence JSON.)")
        print("\n=== Spine (label_cost + throughput + money_opportunities excerpt) ===")
        print(
            json.dumps(
                {
                    "label_cost": {
                        "status": artifact.get("label_cost", {}).get("status"),
                        "row_count": artifact.get("label_cost", {}).get("row_count"),
                        "total_actual_usd": artifact.get("label_cost", {}).get("total_actual_usd"),
                        "delta_usd": artifact.get("label_cost", {}).get("delta_usd"),
                    },
                    "throughput": {
                        "status": artifact.get("throughput", {}).get("status"),
                        "row_count": artifact.get("throughput", {}).get("row_count"),
                    },
                    "money_opportunities_usd": artifact.get("money_opportunities_usd"),
                    "findings_count": len(artifact.get("findings") or []),
                },
                indent=2,
            )
        )
        print("\n=== Grain (tier1 + synthetic_task_count) ===")
        gd = grain.model_dump()
        print(
            json.dumps(
                {
                    "schema_version": gd.get("schema_version"),
                    "synthetic_task_count": gd.get("synthetic_task_count"),
                    "labels": gd.get("labels"),
                    "tasks": gd.get("tasks"),
                    "order_financials": gd.get("order_financials"),
                    "asn": gd.get("asn"),
                    "order_lines": gd.get("order_lines"),
                    "billing": gd.get("billing"),
                    "employees": gd.get("employees"),
                    "join_safety": gd.get("join_safety"),
                },
                indent=2,
            )
        )
        print("\n=== Audit outcome (themes + tier1_row_counts + opportunity) ===")
        od = od_full
        print(
            json.dumps(
                {
                    "schema_version": od.get("schema_version"),
                    "themes": od.get("themes"),
                    "backbone_completeness": {
                        "report_confidence": (od.get("backbone_completeness") or {}).get("report_confidence"),
                        "backbone_score": (od.get("backbone_completeness") or {}).get("backbone_score"),
                        "missing": (od.get("backbone_completeness") or {}).get("missing"),
                    },
                    "competitive_kpis": od.get("competitive_kpis"),
                    "label_network_insights": (
                        ((od.get("current_state") or {}).get("warehouse_intelligence") or {}).get(
                            "label_network_insights"
                        )
                    ),
                    "complementary_network_audit": (
                        ((od.get("current_state") or {}).get("warehouse_intelligence") or {}).get(
                            "complementary_network_audit"
                        )
                    ),
                    "audit_sharpness_metrics": (
                        ((od.get("current_state") or {}).get("warehouse_intelligence") or {}).get(
                            "audit_sharpness_metrics"
                        )
                    ),
                    "current_state": {
                        "tier1_row_counts": (od.get("current_state") or {}).get("tier1_row_counts"),
                        "label_cost_status": (od.get("current_state") or {}).get("label_cost_status"),
                        "throughput_status": (od.get("current_state") or {}).get("throughput_status"),
                    },
                    "opportunity": od.get("opportunity"),
                    "data_quality": {
                        "modules_partial": od.get("data_quality", {}).get("modules_partial"),
                        "upload_opportunities_count": len(
                            (od.get("data_quality") or {}).get("upload_opportunities") or []
                        ),
                    },
                },
                indent=2,
            )
        )
        if order_analysis:
            print("\n=== Order financial analysis (totals snapshot) ===")
            print(
                json.dumps(
                    {
                        "row_count": order_analysis.get("row_count"),
                        "totals": order_analysis.get("totals"),
                    },
                    indent=2,
                )
            )

        if args.with_ai_recommendations:
            print("\n=== NIM (audit AI recommendations) ===")
            key = settings.nvidia_api_key or ""
            print(
                json.dumps(
                    {
                        "nim_base_url": settings.nim_base_url,
                        "nim_model": settings.nim_model,
                        "nvidia_api_key_set": bool(key),
                    },
                    indent=2,
                )
            )
            nim_payload = build_nim_audit_payload(
                outcome_dict=outcome.model_dump(),
                spine_artifact=artifact,
                detail=args.ai_detail,
            )
            ai_block = await generate_audit_ai_recommendations(
                audit_payload=nim_payload,
                detail=args.ai_detail,
            )
            print("\n--- ai_recommendations (includes nim_invocation: how NVIDIA was called) ---")
            print(json.dumps(ai_block, indent=2, default=str))
    finally:
        if engine is not None:
            await engine.dispose()
        Path(path).unlink(missing_ok=True)


if __name__ == "__main__":
    asyncio.run(main())

"""End-to-end mock fixture pipeline (SQLite temp) — same path as scripts/run_audit_mock_fixtures_demo.py."""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

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
from unie_cortex.services.warehouse_intelligence_baseline import build_warehouse_intelligence_baseline
from unie_cortex.services.warehouse_strategy_suggestions import build_warehouse_strategy_suggestions
from unie_cortex.spine.fixture_warehouse_baseline import baseline_candidate_warehouses
from unie_cortex.spine.ingest import ingest_labels_csv
from unie_cortex.spine.mock_audit_enrichment import inject_fbm_pick_pack_billing_rows, summarize_mock_pipeline_checks
from unie_cortex.spine.order_financial_ingest import ingest_order_financials_csv
from unie_cortex.spine.runner import parse_mapping_payload, parse_tier1_mapping_blocks, run_audit_spine
from unie_cortex.spine.tier1_ingest import (
    ingest_asn_csv,
    ingest_billing_lines_csv,
    ingest_employees_csv,
    ingest_order_lines_csv,
)
from unie_cortex.services.synthetic_tasks import ensure_synthetic_tasks_from_tier1

FIX = Path(__file__).resolve().parent / "fixtures" / "audit"


def _truncate(raw: bytes, max_rows: int) -> bytes:
    if max_rows <= 0:
        return raw
    text = raw.decode("utf-8-sig", errors="replace")
    lines = text.splitlines()
    if len(lines) <= 1:
        return raw
    return ("\n".join([lines[0], *lines[1 : max_rows + 1]]) + "\n").encode("utf-8")


def test_mock_audit_full_pipeline_runs_and_exposes_human_readable():
    asyncio.run(_mock_audit_pipeline_once())


async def _mock_audit_pipeline_once() -> None:
    mapping = json.loads((FIX / "column_mapping.json").read_text(encoding="utf-8"))
    ml, mt = parse_mapping_payload(mapping)
    m_asn, m_ol, m_bl, m_emp = parse_tier1_mapping_blocks(mapping)

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    path = tmp.name
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}", echo=False, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(db_models.Base.metadata.create_all)
        SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with SessionLocal() as session:
            store = SqlCortexStore(session)
            eid = "pytest-mock-pipeline"
            await store.engagement_create(eid, "pytest mock", None, None)
            await store.mapping_save(eid, mapping)
            await store.engagement_set_network_context(
                eid,
                {
                    "candidate_warehouses": baseline_candidate_warehouses(),
                    "facility_profile": {
                        "sqft": 185000,
                        "loading_dock": True,
                        "headcount_reported": 42,
                    },
                },
            )
            eng = await store.engagement_get(eid)
            nc = (eng or {}).get("network_context") or {}
            wh_candidates = nc.get("candidate_warehouses") if isinstance(nc.get("candidate_warehouses"), list) else None

            max_rows = 35
            bb = _truncate((FIX / "billing.csv").read_bytes(), max_rows)
            bb = inject_fbm_pick_pack_billing_rows(bb, 40)

            await ingest_labels_csv(
                store, eid, _truncate((FIX / "labels.csv").read_bytes(), max_rows), "labels.csv", ml, candidate_warehouses=wh_candidates
            )
            await ingest_order_financials_csv(
                store, eid, _truncate((FIX / "order_financials.csv").read_bytes(), max_rows), "of.csv", mapping
            )
            await ingest_asn_csv(store, eid, _truncate((FIX / "asn.csv").read_bytes(), max_rows), "asn.csv", m_asn)
            await ingest_order_lines_csv(store, eid, _truncate((FIX / "order_lines.csv").read_bytes(), max_rows), "ol.csv", m_ol)
            await ingest_billing_lines_csv(store, eid, bb, "billing.csv", m_bl)
            await ingest_employees_csv(store, eid, _truncate((FIX / "employees.csv").read_bytes(), max_rows), "emp.csv", m_emp)

            await ensure_synthetic_tasks_from_tier1(store, eid)
            artifact = await run_audit_spine(store, ml, mt, engagement_id=eid, mode="assessment")

            labels = await store.label_facts_list(engagement_id=eid)
            tasks = await store.task_facts_list(engagement_id=eid)
            of_rows = await store.order_financial_facts_list(engagement_id=eid)
            asn_rows = await store.asn_facts_list(eid)
            ol_rows = await store.order_line_facts_list(eid)
            bl_rows = await store.billing_line_facts_list(eid)
            emp_rows = await store.employee_facts_list(eid)

            grain = build_grain_report(
                eid, labels, tasks, of_rows, asn_rows=asn_rows, order_line_rows=ol_rows, billing_rows=bl_rows, employee_rows=emp_rows
            )
            order_analysis = analyze_order_financial_facts(of_rows) if of_rows else None
            nc_full = ((await store.engagement_get(eid)) or {}).get("network_context") or {}
            fp = nc_full.get("facility_profile") if isinstance(nc_full.get("facility_profile"), dict) else {}

            wh_intel = build_warehouse_intelligence_baseline(
                facility_profile=fp,
                labels=labels,
                tasks=tasks,
                asn_rows=asn_rows,
                order_lines=ol_rows,
                billing_rows=bl_rows,
                employee_rows=emp_rows,
                network_context=nc_full if isinstance(nc_full, dict) else {},
            )
            backbone = build_backbone_completeness(
                grain=grain,
                facility_profile=fp if isinstance(fp, dict) else {},
                network_context=nc_full if isinstance(nc_full, dict) else {},
            )
            competitive_kpis = build_competitive_kpis(
                grain=grain,
                warehouse_intelligence=wh_intel,
                order_analysis=order_analysis,
            )
            wh_intel["label_network_insights"] = build_label_network_insights(
                labels=labels,
                network_context=nc_full if isinstance(nc_full, dict) else {},
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
                network_context=nc_full if isinstance(nc_full, dict) else {},
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
                network_context=nc_full if isinstance(nc_full, dict) else {},
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
                facility_profile=fp if isinstance(fp, dict) else {},
                network_context=nc_full if isinstance(nc_full, dict) else {},
                backbone_completeness=backbone,
                competitive_kpis=competitive_kpis,
            )
            await session.commit()

        od = outcome.model_dump()
        assert od.get("human_readable", {}).get("headline")
        assert len(wh_intel.get("strategy_suggestions") or []) >= 1
        assert (wh_intel.get("label_network_insights") or {}).get("schema_version") == "label_network_insights_v1"
        cna = wh_intel.get("complementary_network_audit") or {}
        assert cna.get("schema_version") == "complementary_network_audit_v1"
        assert cna.get("status") in ("complete", "skipped")
        asm = wh_intel.get("audit_sharpness_metrics") or {}
        assert asm.get("schema_version") == "audit_sharpness_metrics_v1"
        assert asm.get("overall_readiness", {}).get("tier") in ("low", "medium", "high")
        assert (wh_intel.get("billing_components_usd") or {}).get("variable_ops_usd", 0) > 0
        bb = od.get("backbone_completeness") or {}
        assert bb.get("schema_version") == "audit_backbone_v1"
        assert bb.get("report_confidence") in ("high", "medium", "low")
        assert isinstance(bb.get("missing"), list)
        kp = od.get("competitive_kpis") or {}
        assert kp.get("schema_version") == "warehouse_competitive_kpis_v1"

        checks = summarize_mock_pipeline_checks(wh_intel, od)
        assert checks["human_headline_present"] is True
        assert checks["strategy_suggestion_count"] >= 1
        assert checks["variable_ops_usd"] is not None and checks["variable_ops_usd"] > 0

        assert len(labels) >= 1
        assert grain.synthetic_task_count > 0
        assert artifact.get("label_cost", {}).get("status") == "complete"
    finally:
        await engine.dispose()
        Path(path).unlink(missing_ok=True)

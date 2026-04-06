"""Unit tests for audit AI recommendations block (LLM disabled)."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

from unie_cortex.config import settings
from unie_cortex.services.nim_warehouse_audit import (
    build_nim_audit_payload,
    generate_audit_ai_recommendations,
    parse_nim_recommendations_json,
)


def test_parse_nim_recommendations_json_strips_fence():
    raw = '```json\n{"recommendations":[]}\n```'
    assert parse_nim_recommendations_json(raw) == {"recommendations": []}


def test_build_nim_audit_payload_shape():
    outcome = {
        "human_readable": {"headline": "H", "summary_lines": ["a"], "at_a_glance": []},
        "data_quality": {"upload_opportunities": [{"priority": "high", "category": "billing", "title": "T"}]},
        "current_state": {
            "warehouse_intelligence": {"fulfillment_economics": {"estimated_cost_per_fulfillment_usd": 3.1}},
            "improvement_program": {"schema_version": "improvement_program_v1", "intro": "Test", "items": []},
        },
        "backbone_completeness": {"missing": []},
        "competitive_kpis": {"estimated_handle_usd": 3.1},
        "opportunity": {},
        "themes": [],
    }
    spine = {"label_cost": {"status": "complete"}, "findings": [], "money_opportunities_usd": {}}
    p = build_nim_audit_payload(outcome_dict=outcome, spine_artifact=spine, detail="brief")
    assert p["citation_root"] == "nim_audit_payload"
    assert "complementary_network_audit" in p
    assert p["complementary_network_audit"] == {}
    assert p.get("improvement_program", {}).get("schema_version") == "improvement_program_v1"
    assert "audit_sharpness_metrics" in p
    assert p["backbone_completeness"] == outcome["backbone_completeness"]
    assert p["spine_excerpt"]["label_cost"]["status"] == "complete"


def test_generate_audit_ai_recommendations_llm_disabled():
    async def _run():
        return await generate_audit_ai_recommendations(audit_payload={"x": 1}, detail="brief")

    out = asyncio.run(_run())
    assert out["source"] == "nim_llm_disabled"
    assert isinstance(out["items"], list)
    inv = out.get("nim_invocation") or {}
    assert inv.get("provider") == "none"
    assert inv.get("attempted") is False


def test_generate_audit_ai_disabled_without_key_same_shape():
    async def _run():
        with patch.object(settings, "nvidia_api_key", ""):
            return await generate_audit_ai_recommendations(audit_payload={}, detail="brief")

    out = asyncio.run(_run())
    assert out["source"] == "nim_llm_disabled"
    assert isinstance(out["items"], list)
    assert (out.get("nim_invocation") or {}).get("attempted") is False


def test_generate_audit_ai_recommendations_deterministic_items_present_for_signals():
    payload = {
        "audit_sharpness_metrics": {"overall_readiness": {"tier": "low", "score_0_1": 0.42}},
        "warehouse_intelligence_excerpt": {
            "fulfillment_economics": {"naive_per_event_implausible_vs_reference": True}
        },
        "complementary_network_audit": {"aggregate_delta_usd_per_line_out_of_region": 1.25},
        "upload_opportunities": [{"title": "Upload billing"}, {"title": "Upload employees"}],
    }

    async def _run():
        return await generate_audit_ai_recommendations(audit_payload=payload, detail="brief")

    out = asyncio.run(_run())
    assert out["source"] == "nim_llm_disabled"
    assert isinstance(out["items"], list)
    assert len(out["items"]) >= 1
    assert any("category" in x for x in out["items"] if isinstance(x, dict))

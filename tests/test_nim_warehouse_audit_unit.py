"""Unit tests for NIM audit synthesis (mocked HTTP)."""

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


def test_generate_audit_ai_recommendations_mocked_nim():
    _nim_body = {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"recommendations":[{"title":"Cut fixed review","rationale":"Because fixed share is high",'
                                '"impact_axis":"margin","evidence":[{"path":"nim_audit_payload.competitive_kpis",'
                                '"value":{}}],"risk_notes":""}]}'
                            )
                        }
                    }
                ]
            }

    class _Resp:
        status_code = 200
        text = json.dumps(_nim_body)

        def json(self):
            return _nim_body

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *args, **kwargs):
            return _Resp()

    async def _run():
        with patch.object(settings, "nvidia_api_key", "test-key"):
            with patch("unie_cortex.integrations.nim_chat.httpx.AsyncClient", return_value=_Client()):
                return await generate_audit_ai_recommendations(audit_payload={"x": 1}, detail="brief")

    out = asyncio.run(_run())
    assert out["source"] == "nim"
    assert len(out["items"]) == 1
    assert out["items"][0].get("title") == "Cut fixed review"
    inv = out.get("nim_invocation") or {}
    assert inv.get("provider") == "nvidia_nim"
    assert inv.get("attempted") is True
    assert "chat/completions" in (inv.get("endpoint_url") or "")


def test_generate_audit_ai_skipped_without_key():
    async def _run():
        with patch.object(settings, "nvidia_api_key", ""):
            return await generate_audit_ai_recommendations(audit_payload={}, detail="brief")

    out = asyncio.run(_run())
    assert out["source"] == "skipped_no_key"
    assert out["items"] == []
    assert (out.get("nim_invocation") or {}).get("attempted") is False

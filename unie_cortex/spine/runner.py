"""Run full audit spine -> JSON artifact (deterministic)."""

import json
from datetime import datetime, timezone
from typing import Any

from unie_cortex.db.store import CortexStore
from unie_cortex.spine.coverage import (
    coverage_discrepancy,
    coverage_item_intelligence,
    coverage_label,
    coverage_throughput,
)
from unie_cortex.spine.modules.discrepancy import analyze_discrepancies
from unie_cortex.spine.modules.label_cost import analyze_label_cost
from unie_cortex.spine.modules.sku_velocity import analyze_sku_velocity
from unie_cortex.spine.modules.throughput import analyze_throughput
from unie_cortex.services.analysis_views import attach_four_views_and_pipeline


def parse_mapping_payload(raw: dict) -> tuple[dict, dict]:
    if "labels" in raw and isinstance(raw["labels"], dict):
        return dict(raw["labels"]), dict(raw.get("tasks") or {})
    if any(isinstance(v, dict) for v in raw.values()):
        return {}, {}
    vals = set(raw.values())
    if "completed_at" in vals or ("zone" in vals and "label_amount_usd" not in vals):
        return {}, dict(raw)
    return dict(raw), {}


def parse_tier1_mapping_blocks(raw: dict) -> tuple[dict[str, str], dict[str, str], dict[str, str], dict[str, str]]:
    """Return asn, order_lines, billing, employees column maps from engagement mapping JSON."""

    def blk(key: str) -> dict[str, str]:
        d = raw.get(key) if isinstance(raw, dict) else None
        if not isinstance(d, dict):
            return {}
        return {
            str(k): str(v)
            for k, v in d.items()
            if str(k).strip() and str(v).strip()
        }

    return blk("asn"), blk("order_lines"), blk("billing"), blk("employees")


async def run_audit_spine(
    store: CortexStore,
    mappings_labels: dict[str, str],
    mappings_tasks: dict[str, str],
    engagement_id: str | None = None,
    tenant_id: str | None = None,
    warehouse_id: str | None = None,
    mode: str = "assessment",
) -> dict[str, Any]:
    lc_status, lc_missing = coverage_label(mappings_labels)
    tp_status, tp_missing = coverage_throughput(mappings_tasks)
    disc_status, disc_missing = coverage_discrepancy(mappings_labels)
    iv_status, iv_missing = coverage_item_intelligence(mappings_labels, mappings_tasks)

    label_result = await analyze_label_cost(
        store, engagement_id, tenant_id, warehouse_id, lc_status, lc_missing
    )
    throughput_result = await analyze_throughput(
        store, engagement_id, tenant_id, warehouse_id, tp_status, tp_missing
    )
    disc_result = await analyze_discrepancies(
        store, engagement_id, tenant_id, warehouse_id, disc_status, disc_missing
    )
    sku_vel_result = await analyze_sku_velocity(
        store, engagement_id, tenant_id, warehouse_id, iv_status, iv_missing
    )

    opp = label_result.get("opportunity_if_shopped_usd") or {}
    money_low = opp.get("low")
    money_high = opp.get("high")

    findings = list(disc_result.get("findings") or [])
    if label_result.get("status") == "complete" and (label_result.get("delta_usd") or 0) > 0:
        findings.append(
            {
                "type": "label_spend_above_benchmark",
                "severity": "medium",
                "delta_usd": label_result.get("delta_usd"),
                "message": "Aggregate label spend exceeds heuristic benchmark — rate-shopping may reduce 3PL pass-through.",
            }
        )
    if throughput_result.get("bottleneck_zones_top5"):
        top = throughput_result["bottleneck_zones_top5"][0]
        findings.append(
            {
                "type": "zone_concentration",
                "severity": "low",
                "zone": top.get("zone"),
                "count": top.get("count"),
                "message": "Task volume concentrated in one zone — review slotting and labor balance.",
            }
        )
    if sku_vel_result.get("status") == "complete" and sku_vel_result.get("top_skus"):
        ts = sku_vel_result["top_skus"][:3]
        findings.append(
            {
                "type": "sku_velocity_signal",
                "severity": "low",
                "top_skus": ts,
                "message": f"Top SKUs by label/task signals: {', '.join(s.get('sku','') for s in ts)} — use for slotting / allocation.",
            }
        )

    art: dict[str, Any] = {
        "version": 1,
        "mode": mode,
        "engagement_id": engagement_id,
        "tenant_id": tenant_id,
        "warehouse_id": warehouse_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "coverage": {
            "label_cost_module": {"status": lc_status, "missing": lc_missing},
            "throughput_module": {"status": tp_status, "missing": tp_missing},
            "discrepancy_module": {"status": disc_status, "missing": disc_missing},
            "item_intelligence_module": {"status": iv_status, "missing": iv_missing},
        },
        "label_cost": label_result,
        "throughput": throughput_result,
        "discrepancies": disc_result,
        "sku_velocity": sku_vel_result,
        "findings": findings,
        "money_opportunities_usd": {
            "low": money_low,
            "high": money_high,
            "note": "Derived from spine only; NIM does not invent these numbers.",
        },
    }
    current_payload = {
        "schema_version": "assessment_current_v1",
        "engagement_id": engagement_id,
        "note": "As-is mapped facts and spine inputs before Unie recommendations.",
        "coverage": art["coverage"],
    }
    attach_four_views_and_pipeline(art, current_payload=current_payload)
    return art


def artifact_to_json(artifact: dict) -> str:
    return json.dumps(artifact, default=str)

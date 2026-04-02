"""
Build structured BEFORE / AFTER operational proposals from the audit spine.
Ground truth = artifact numbers; proposed actions are playbook templates tied to findings.
"""

from __future__ import annotations

import json
from typing import Any


def _zones_from_throughput(tp: dict) -> list[dict]:
    return list(tp.get("bottleneck_zones_top5") or [])[:5]


def build_before_after_proposal(artifact: dict[str, Any]) -> dict[str, Any]:
    """
    Returns {
      before: { headline, metrics, employee_efficiency, routing, cost_to_operate, gaps },
      after: { headline, routing, efficiency_labor, cost_shipping, auto_tasks, approval_checklist },
      diff_lines: [str] for side-by-side UI
    }
    """
    lc = artifact.get("label_cost") or {}
    tp = artifact.get("throughput") or {}
    sv = artifact.get("sku_velocity") or {}
    findings = list(artifact.get("findings") or [])
    money = artifact.get("money_opportunities_usd") or {}
    zones = _zones_from_throughput(tp)
    top_zone = zones[0] if zones else None

    before_metrics = {
        "label_module_status": lc.get("status"),
        "throughput_module_status": tp.get("status"),
        "sku_velocity_module_status": sv.get("status"),
        "sku_velocity_top": sv.get("top_skus") or [],
        "total_label_spend_usd": lc.get("total_actual_usd"),
        "benchmark_label_spend_usd": lc.get("total_benchmark_usd"),
        "label_delta_usd": lc.get("delta_usd"),
        "label_rows_analyzed": lc.get("row_count"),
        "task_rows_analyzed": tp.get("row_count"),
        "hot_zones": [{"zone": z.get("zone"), "task_count": z.get("count")} for z in zones],
        "money_opportunity_band_usd": {"low": money.get("low"), "high": money.get("high")},
    }

    emp_notes: list[str] = []
    if top_zone:
        emp_notes.append(
            f"Heavy task concentration in zone **{top_zone.get('zone')}** "
            f"({top_zone.get('count')} tasks) — risk of picker idle/wait imbalance across shifts."
        )
    if tp.get("status") == "skipped":
        emp_notes.append("Task/throughput data incomplete — labor efficiency cannot be fully scored.")

    routing_notes: list[str] = []
    if len(zones) >= 2:
        routing_notes.append(
            "Pick/route density skewed; consider wave or batch rules that spread volume across zones."
        )
    elif top_zone:
        routing_notes.append(
            f"Prioritize slotting review for zone **{top_zone.get('zone')}** to shorten pick path."
        )
    else:
        routing_notes.append("Insufficient zone-level task data for routing optimization.")

    gaps = [{"type": f.get("type"), "message": f.get("message"), "severity": f.get("severity")} for f in findings]

    before = {
        "headline": "Current operating picture (from your uploaded / live facts)",
        "metrics": before_metrics,
        "employee_efficiency": emp_notes,
        "routing": routing_notes,
        "cost_to_operate": {
            "shipping_label_component_usd_actual": lc.get("total_actual_usd"),
            "vs_benchmark_delta_usd": lc.get("delta_usd"),
            "recoverable_band_estimate_usd": {"low": money.get("low"), "high": money.get("high")},
            "note": money.get("note") or "Band derived from spine benchmark, not a guarantee.",
        },
        "gaps_and_findings": gaps,
    }

    # AFTER: proposed actions (user must approve before execution playbook)
    routing_actions: list[dict] = []
    if top_zone:
        routing_actions.append(
            {
                "id": "route_1",
                "category": "routing",
                "title": f"Rebalance pick waves for zone {top_zone.get('zone')}",
                "detail": "Shift 10–20% of single-zone batches to multi-zone waves where WMS allows.",
                "expected_impact": "Shorter peak travel per picker; fewer bottlenecks at zone entry.",
                "priority": "high" if (top_zone.get("count") or 0) > 100 else "medium",
            }
        )
    top_names = [s.get("sku") for s in (sv.get("top_skus") or [])[:5] if s.get("sku")]
    route_2_detail = (
        f"Spine SKU signals: {', '.join(top_names)} — slot these within 1 hop of primary pack lane."
        if top_names
        else "Run ABC velocity report; move top SKUs within 1 hop of primary pack lane."
    )
    routing_actions.append(
        {
            "id": "route_2",
            "category": "routing",
            "title": "Slot fast-movers closer to pack/stage",
            "detail": route_2_detail,
            "expected_impact": "Reduced pick time per order.",
            "priority": "high" if top_names else "medium",
        }
    )

    efficiency_actions: list[dict] = []
    efficiency_actions.append(
        {
            "id": "eff_1",
            "category": "efficiency_labor",
            "title": "Labor leveling by zone",
            "detail": "Staff pickers proportionally to zone task share; cross-train 2 backup zones.",
            "expected_impact": "Lower overtime on hot zones; higher utilization on cold zones.",
            "priority": "high" if top_zone else "medium",
        }
    )

    cost_actions: list[dict] = []
    delta = lc.get("delta_usd") or 0
    if lc.get("status") == "complete" and delta > 0:
        cost_actions.append(
            {
                "id": "cost_1",
                "category": "cost_shipping",
                "title": "Enforce rate-shopping at label purchase",
                "detail": f"Spine shows ~${round(delta, 2)} aggregate delta vs benchmark — carrier/service mix review.",
                "expected_impact": f"Target recoverable band ${money.get('low')}–${money.get('high')} USD (heuristic).",
                "priority": "high",
            }
        )
    cost_actions.append(
        {
            "id": "cost_2",
            "category": "cost_shipping",
            "title": "Audit 3PL pass-through vs contract",
            "detail": "Compare billed label $ to spine benchmark weekly.",
            "expected_impact": "Catch carrier markup drift.",
            "priority": "medium",
        }
    )

    auto_tasks: list[dict] = [
        {
            "id": "auto_0",
            "category": "automation",
            "title": "Product Research Optimization run (catalog + Keepa demand + allocation)",
            "schedule": "weekly",
            "owner_role": "inventory_lead",
            "system_hook": "POST /v1/operational/{tenant}/{warehouse}/product-research-optimization/run",
            "action_on_trigger": "Review recommended monthly units per 3PL node and transfer cost band",
        },
        {
            "id": "auto_1",
            "category": "automation",
            "title": "Weekly label-cost benchmark job",
            "schedule": "weekly",
            "owner_role": "shipping_lead",
            "system_hook": "Cortex operational facts + spine",
            "action_on_trigger": "If delta_usd > threshold, open MAIW proposal draft",
        },
        {
            "id": "auto_2",
            "category": "automation",
            "title": "Zone throughput alert",
            "schedule": "daily",
            "owner_role": "ops_manager",
            "system_hook": "task_facts ingest",
            "action_on_trigger": "If single zone > 40% of tasks, notify supervisor",
        },
        {
            "id": "auto_3",
            "category": "automation",
            "title": "Post-approval playbook export",
            "schedule": "on_approve",
            "owner_role": "WMS_admin",
            "system_hook": "MAIW proposal approved",
            "action_on_trigger": "Push checklist to ticketing or WMS change log (integrate externally)",
        },
    ]

    after = {
        "headline": "Proposed operating changes (pending manager approval)",
        "routing": routing_actions,
        "efficiency_labor": efficiency_actions,
        "cost_shipping": cost_actions,
        "auto_tasks": auto_tasks,
        "approval_checklist": [
            "Confirm proposed routing changes are feasible in current WMS version.",
            "Confirm labor plan signed off by site lead.",
            "Confirm cost actions align with carrier contracts.",
            "Auto-tasks above: approve which jobs to enable in Cortex / external scheduler.",
        ],
    }

    diff_lines = [
        "**Cost:** Before = actual label $ and delta vs benchmark; After = rate-shop enforcement + audit cadence.",
        "**Routing:** Before = hot-zone concentration; After = wave/slotting actions.",
        "**Efficiency:** Before = load skew; After = leveling + cross-training.",
        "**Automation:** After adds scheduled jobs — approve each auto_task id you want active.",
    ]

    return {"before": before, "after": after, "diff_lines": diff_lines}


async def attach_nim_rationale(
    artifact: dict,
    before_after: dict,
    *,
    store=None,
    tenant_id: str | None = None,
    engagement_id: str | None = None,
    run_id: str | None = None,
) -> tuple[str | None, str]:
    """Short executive rationale only; does not mutate structured before/after numbers."""
    from unie_cortex.services.nim_narrative import generate_narrative_from_artifact

    slim = {
        "task": "Write 2 short paragraphs: (1) why the BEFORE state matters for cost and labor. "
        "(2) why the AFTER proposals are logical follow-ons. Use only facts from before/after JSON.",
        "before_headline": before_after["before"].get("headline"),
        "metrics": before_after["before"].get("metrics"),
        "after_counts": {
            "routing": len(before_after["after"].get("routing") or []),
            "efficiency": len(before_after["after"].get("efficiency_labor") or []),
            "cost": len(before_after["after"].get("cost_shipping") or []),
            "auto_tasks": len(before_after["after"].get("auto_tasks") or []),
        },
        "artifact_money": artifact.get("money_opportunities_usd"),
    }
    text, src = await generate_narrative_from_artifact(
        slim,
        store=store,
        capability="maiw_proposal_rationale",
        tenant_id=tenant_id,
        engagement_id=engagement_id,
        run_id=run_id,
    )
    return text, src

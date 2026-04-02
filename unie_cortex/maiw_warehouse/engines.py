"""Internal + original decision builders for Warehouse Intelligence capabilities."""

from __future__ import annotations

import statistics
from datetime import datetime
from typing import Any

from unie_cortex.maiw_warehouse.schemas import (
    BatchPickPathRequest,
    BillingAnomalyRequest,
    BillingExplainRequest,
    LaborCapacityRequest,
    LaborStaffingRequest,
    PrioritizeQueueRequest,
    SuggestPutawayRequest,
    WaveSuggestRequest,
)


def pick_path_original(req: BatchPickPathRequest) -> dict[str, Any]:
    ordered = sorted(req.stops, key=lambda s: (s.location_code or s.stop_id or "").upper())
    return {"orderedStopIds": [s.stop_id for s in ordered], "method": "alphabetical_location"}


def pick_path_internal(req: BatchPickPathRequest) -> dict[str, Any]:
    """Zone/aisle heuristic: sort by location_code prefix (e.g. A-01 before B-02)."""
    def key(s):
        loc = (s.location_code or s.stop_id or "").upper()
        return (loc[:1], loc)

    ordered = [s.stop_id for s in sorted(req.stops, key=key)]
    return {"orderedStopIds": ordered, "method": "zone_aisle_heuristic"}


def merge_pick_orders(internal_ids: list[str], nvidia_ids: list[str] | None) -> dict[str, Any]:
    if not nvidia_ids:
        return {"orderedStopIds": internal_ids, "method": "internal_only"}
    # Simple merge: use NVIDIA order where it matches set; else internal
    sset = set(internal_ids)
    merged = [i for i in nvidia_ids if i in sset]
    for i in internal_ids:
        if i not in merged:
            merged.append(i)
    return {"orderedStopIds": merged, "method": "internal_plus_nvidia_merge"}


def labor_capacity_original(req: LaborCapacityRequest) -> dict[str, Any]:
    total_rate = sum((e.tasks_per_hour_historical or 0) for e in req.employees)
    return {
        "expectedTasksPerHour": round(total_rate, 2),
        "method": "sum_historical_rates",
    }


def labor_capacity_internal(req: LaborCapacityRequest) -> dict[str, Any]:
    now = datetime.fromisoformat(req.now_iso.replace("Z", "+00:00"))
    total_tasks_remaining_shift = 0.0
    detail = []
    for e in req.employees:
        rate = e.tasks_per_hour_historical or 12.0
        hours_left = 4.0
        if e.scheduled_shift_end:
            try:
                end = datetime.fromisoformat(e.scheduled_shift_end.replace("Z", "+00:00"))
                hours_left = max(0.0, (end - now).total_seconds() / 3600.0)
            except Exception:
                pass
        checked_in = bool(e.check_in_sessions)
        eff = rate if checked_in else rate * 0.0
        contrib = eff * hours_left
        total_tasks_remaining_shift += contrib
        detail.append(
            {
                "employeeId": e.employee_id,
                "checkedIn": checked_in,
                "hoursRemaining": round(hours_left, 2),
                "expectedTasks": round(contrib, 1),
            }
        )
    return {
        "expectedTasksRemainingShift": round(total_tasks_remaining_shift, 1),
        "employeeBreakdown": detail,
        "pendingTaskCount": req.pending_task_count,
        "method": "rate_times_hours_checked_in",
    }


def staffing_original(req: LaborStaffingRequest) -> dict[str, Any]:
    checked = sum(1 for e in req.employees if e.check_in_sessions)
    return {"headcountCheckedIn": checked, "recommendation": "no_change", "method": "baseline"}


def staffing_internal(req: LaborStaffingRequest) -> dict[str, Any]:
    rate = statistics.mean([(e.tasks_per_hour_historical or 10.0) for e in req.employees] or [10.0])
    checked = max(1, sum(1 for e in req.employees if e.check_in_sessions))
    capacity_per_hour = rate * checked
    demand_units = req.pending_task_count + req.orders_pending_pack * 3
    gap_hours = max(0.0, demand_units / max(0.1, capacity_per_hour) - 1.0)
    need = int(gap_hours // 2) if gap_hours > 2 else 0
    cost_note = None
    pays = [e.hourly_pay for e in req.employees if e.hourly_pay]
    if pays and need > 0:
        avg_pay = statistics.mean(pays)
        cost_note = f"~${avg_pay * need * 8:.0f}/day rough (8h x {need} @ avg pay)"
    oms = req.oms_demand_hints
    oms_note = None
    if oms and oms.projected_order_rate_per_hour:
        oms_note = "OMS hints present (upgrade will weight spike prediction)."
    return {
        "seasonalEquivalentsSuggested": need,
        "confidence": 0.55 if need else 0.75,
        "demandUnits": demand_units,
        "capacityPerHour": round(capacity_per_hour, 2),
        "costBandNote": cost_note,
        "omsNote": oms_note,
        "method": "queue_over_capacity_heuristic",
    }


def prioritize_original(req: PrioritizeQueueRequest) -> dict[str, Any]:
    ids = [j.job_id for j in req.jobs]
    return {"orderedJobIds": ids, "method": "fifo_input_order"}


def wave_suggest_original(req: WaveSuggestRequest) -> dict[str, Any]:
    n = min(10, len(req.jobs))
    return {"waveJobIds": [j.job_id for j in req.jobs[:n]], "method": "fifo_first_n"}


def wave_suggest_internal(req: WaveSuggestRequest) -> dict[str, Any]:
    pq = PrioritizeQueueRequest(
        meta=req.meta,
        now_iso=req.now_iso,
        jobs=req.jobs,
        courier_cutoffs=req.courier_cutoffs,
    )
    pr = prioritize_internal(pq)
    checked = max(1, sum(1 for e in req.employees if e.check_in_sessions))
    k = min(len(pr["orderedJobIds"]), max(5, checked * 8))
    return {
        "waveJobIds": pr["orderedJobIds"][:k],
        "priorityReasons": pr.get("reasons"),
        "method": "priority_capped_by_checkedin_headcount",
    }


def prioritize_internal(req: PrioritizeQueueRequest) -> dict[str, Any]:
    now = datetime.fromisoformat(req.now_iso.replace("Z", "+00:00"))

    def score(j):
        s = 0.0
        for raw in (j.carrier_cutoff_at, j.ship_by, j.due_at):
            if not raw:
                continue
            try:
                t = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                hours = (t - now).total_seconds() / 3600.0
                if hours < 0:
                    s += 1000
                else:
                    s += max(0, 100 - hours)
            except Exception:
                pass
        return -s

    ordered = [j.job_id for j in sorted(req.jobs, key=score)]
    reasons = {j.job_id: "cutoff_or_due_proximity" for j in req.jobs}
    return {"orderedJobIds": ordered, "reasons": reasons, "method": "urgency_score"}


def putaway_original(_req: SuggestPutawayRequest) -> dict[str, Any]:
    return {"assignments": [], "method": "no_op"}


def putaway_internal(req: SuggestPutawayRequest) -> dict[str, Any]:
    assigns = []
    locs = req.candidate_locations or [{"locationCode": "DEFAULT-A-01", "zone": "A"}]
    for i, line in enumerate(req.lines):
        loc = locs[i % len(locs)]
        assigns.append({"sku": line.sku, "suggestedLocation": loc.get("locationCode"), "reason": "round_robin_candidate"})
    return {"assignments": assigns, "method": "velocity_aware_stub"}


def billing_explain_original(req: BillingExplainRequest) -> dict[str, Any]:
    return {"lines": [{"lineId": l.line_id, "summary": "No AI"} for l in req.lines]}


def billing_explain_internal(req: BillingExplainRequest) -> dict[str, Any]:
    out = []
    for l in req.lines:
        out.append(
            {
                "lineId": l.line_id,
                "summary": f"Charge {l.code or 'LINE'} amount ${l.amount:.2f} vs profile baseline (deterministic stub).",
            }
        )
    return {"lines": out, "method": "rule_template"}


def billing_anomaly_original(_req: BillingAnomalyRequest) -> dict[str, Any]:
    return {"flags": [], "method": "no_rules_engine"}


def billing_anomaly_internal(req: BillingAnomalyRequest) -> dict[str, Any]:
    amounts = [l.amount for l in req.lines]
    if not amounts:
        return {"flags": [], "method": "empty"}
    med = statistics.median(amounts)
    flags = []
    for l in req.lines:
        if med > 0 and l.amount > 3 * med:
            flags.append({"lineId": l.line_id, "severity": "high", "reason": "amount_gt_3x_median"})
    return {"flags": flags, "median": med, "method": "median_multiplier"}


def support_stub_response(audience: str, last_user_message: str) -> dict[str, Any]:
    return {
        "reply": (
            f"[Warehouse Intelligence support stub — audience={audience}] "
            "Connect RAG + tool calls to WMS read APIs. User said: "
            + last_user_message[:200]
        ),
        "escalate": False,
        "suggestedProposalType": None,
    }

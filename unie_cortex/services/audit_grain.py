"""Grain and coverage reconciliation for assessment engagements."""

from __future__ import annotations

from typing import Any

from unie_cortex.services.audit_contracts import (
    AuditGrainReport,
    GrainFamilySummary,
    JoinSafety,
)


def _minmax_dates(values: list[str | None]) -> tuple[str | None, str | None]:
    xs = sorted({v for v in values if v and str(v).strip()})
    if not xs:
        return None, None
    return xs[0], xs[-1]


def _nonempty_frac(rows: list[dict], key: str) -> float:
    if not rows:
        return 0.0
    n = sum(1 for r in rows if r.get(key) not in (None, ""))
    return round(n / len(rows), 4)


def build_grain_report(
    engagement_id: str | None,
    labels: list[dict],
    tasks: list[dict],
    order_financials: list[dict],
    *,
    asn_rows: list[dict] | None = None,
    order_line_rows: list[dict] | None = None,
    billing_rows: list[dict] | None = None,
    employee_rows: list[dict] | None = None,
) -> AuditGrainReport:
    asn_rows = asn_rows or []
    order_line_rows = order_line_rows or []
    billing_rows = billing_rows or []
    employee_rows = employee_rows or []

    l_dates = [r.get("ship_date") for r in labels]
    t_dates = [r.get("completed_at") for r in tasks]
    o_dates = [r.get("order_date_iso") for r in order_financials]
    a_dates = [r.get("received_at_iso") or r.get("expected_at_iso") for r in asn_rows]
    ol_dates = [r.get("shipped_at_iso") or r.get("ordered_at_iso") for r in order_line_rows]
    b_dates = [r.get("service_start_iso") or r.get("service_end_iso") for r in billing_rows]
    e_dates = [r.get("hire_date_iso") for r in employee_rows]

    lmin, lmax = _minmax_dates([str(x) if x is not None else None for x in l_dates])
    tmin, tmax = _minmax_dates([str(x) if x is not None else None for x in t_dates])
    omin, omax = _minmax_dates([str(x) if x is not None else None for x in o_dates])
    amin, amax = _minmax_dates([str(x) if x is not None else None for x in a_dates])
    olmin, olmax = _minmax_dates([str(x) if x is not None else None for x in ol_dates])
    bmin, bmax = _minmax_dates([str(x) if x is not None else None for x in b_dates])
    emin, emax = _minmax_dates([str(x) if x is not None else None for x in e_dates])

    synthetic_n = sum(
        1
        for r in tasks
        if isinstance(r.get("extra"), dict) and (r.get("extra") or {}).get("provenance") == "synthetic"
    )

    labels_join = {
        "sku": _nonempty_frac(labels, "sku") >= 0.15,
        "tracking_number": _nonempty_frac(labels, "tracking_number") >= 0.5,
        "dest_postal": _nonempty_frac(labels, "dest_postal") >= 0.5,
    }
    tasks_join = {
        "zone": _nonempty_frac(tasks, "zone") >= 0.5,
        "sku": _nonempty_frac(tasks, "sku") >= 0.15,
    }
    of_join = {
        "sku": _nonempty_frac(order_financials, "sku") >= 0.15,
        "order_external_id": _nonempty_frac(order_financials, "order_external_id") >= 0.5,
    }
    asn_join = {
        "asn_line_id": _nonempty_frac(asn_rows, "asn_line_id") >= 0.5,
        "sku": _nonempty_frac(asn_rows, "sku") >= 0.15,
        "received_at_iso": _nonempty_frac(asn_rows, "received_at_iso") >= 0.25,
    }
    ol_join = {
        "order_external_id": _nonempty_frac(order_line_rows, "order_external_id") >= 0.5,
        "sku": _nonempty_frac(order_line_rows, "sku") >= 0.15,
        "shipped_at_iso": _nonempty_frac(order_line_rows, "shipped_at_iso") >= 0.25,
    }
    bill_join = {
        "invoice_id": _nonempty_frac(billing_rows, "invoice_id") >= 0.5,
        "amount_usd": _nonempty_frac(billing_rows, "amount_usd") >= 0.5,
    }
    emp_join = {
        "employee_id": _nonempty_frac(employee_rows, "employee_id") >= 0.9,
        "role": _nonempty_frac(employee_rows, "role") >= 0.5,
    }

    sku_l = labels_join["sku"]
    sku_o = of_join["sku"]
    oid_o = of_join["order_external_id"]

    join = JoinSafety(
        labels_to_orders_via_sku="ok"
        if sku_l and sku_o and _nonempty_frac(labels, "sku") >= 0.25 and _nonempty_frac(order_financials, "sku") >= 0.25
        else ("weak" if sku_l and sku_o else "unavailable"),
        labels_to_orders_via_order_id="unavailable",
        tasks_to_labels_via_sku="ok"
        if sku_l and tasks_join["sku"]
        else ("weak" if (sku_l or tasks_join["sku"]) else "unavailable"),
        notes=[],
    )
    if not labels:
        join.notes.append("No label facts — shipping/courier synthesis is limited.")
    if not tasks:
        join.notes.append("No task facts — throughput synthesis is limited.")
    if not order_financials:
        join.notes.append("No order financial facts — order economics synthesis is limited.")
    if not asn_rows and not order_line_rows:
        join.notes.append("No ASN or order-line facts — inbound/outbound operational grain is thin.")
    if len(tasks) > 0 and synthetic_n == len(tasks):
        join.notes.append(
            "Task facts are synthetic (derived from ASN/order lines) — confirm timestamps before labor modeling."
        )

    return AuditGrainReport(
        engagement_id=engagement_id,
        labels=GrainFamilySummary(
            row_count=len(labels), date_min=lmin, date_max=lmax, join_keys_present=labels_join
        ),
        tasks=GrainFamilySummary(
            row_count=len(tasks), date_min=tmin, date_max=tmax, join_keys_present=tasks_join
        ),
        order_financials=GrainFamilySummary(
            row_count=len(order_financials),
            date_min=omin,
            date_max=omax,
            join_keys_present=of_join,
        ),
        asn=GrainFamilySummary(
            row_count=len(asn_rows), date_min=amin, date_max=amax, join_keys_present=asn_join
        ),
        order_lines=GrainFamilySummary(
            row_count=len(order_line_rows), date_min=olmin, date_max=olmax, join_keys_present=ol_join
        ),
        billing=GrainFamilySummary(
            row_count=len(billing_rows), date_min=bmin, date_max=bmax, join_keys_present=bill_join
        ),
        employees=GrainFamilySummary(
            row_count=len(employee_rows), date_min=emin, date_max=emax, join_keys_present=emp_join
        ),
        synthetic_task_count=synthetic_n,
        join_safety=join,
    )


def grain_report_to_dict(report: AuditGrainReport) -> dict[str, Any]:
    return report.model_dump()

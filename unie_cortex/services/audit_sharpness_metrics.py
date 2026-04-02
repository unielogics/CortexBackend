"""
Ultra-sharp audit metrics with **partial-data tolerance**.

WMS and billing exports rarely share the same column set. We only compute each metric when
prerequisite fields exist; otherwise we return ``status: unavailable`` or ``partial`` with
``missing_fields`` / ``notes`` so NIM and UI can caveat claims instead of failing.
"""

from __future__ import annotations

from typing import Any

from unie_cortex.services.audit_contracts import AuditGrainReport
from unie_cortex.services.warehouse_intelligence_baseline import REFERENCE_TYPICAL_ORDER_HANDLE_USD


def _nonempty_frac(rows: list[dict], key: str) -> float:
    if not rows:
        return 0.0
    n = sum(1 for r in rows if r.get(key) not in (None, ""))
    return round(n / len(rows), 4)


def _feed_keys(rows: list[dict], keys: list[str]) -> dict[str, float]:
    return {k: _nonempty_frac(rows, k) for k in keys}


def _m(
    *,
    status: str,
    value: Any = None,
    unit: str | None = None,
    coverage: float | None = None,
    missing_fields: list[str] | None = None,
    methodology: str | None = None,
    notes: list[str] | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {"status": status}
    if value is not None:
        out["value"] = value
    if unit:
        out["unit"] = unit
    if coverage is not None:
        out["coverage"] = coverage
    if missing_fields:
        out["missing_fields"] = missing_fields
    if methodology:
        out["methodology"] = methodology
    if notes:
        out["notes"] = notes
    return out


def _tier_from_scores(scores: list[float | None]) -> tuple[str, float]:
    """scores in [0,1] or None — overall readiness tier and mean of available."""
    xs = [x for x in scores if x is not None]
    if not xs:
        return "low", 0.0
    m = sum(xs) / len(xs)
    if m >= 0.72:
        return "high", round(m, 3)
    if m >= 0.45:
        return "medium", round(m, 3)
    return "low", round(m, 3)


def build_audit_sharpness_metrics(
    *,
    labels: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    order_lines: list[dict[str, Any]],
    billing_rows: list[dict[str, Any]],
    order_financials: list[dict[str, Any]],
    asn_rows: list[dict[str, Any]],
    employee_rows: list[dict[str, Any]],
    grain: AuditGrainReport,
    warehouse_intelligence: dict[str, Any] | None,
    competitive_kpis: dict[str, Any] | None,
    order_analysis: dict[str, Any] | None,
    backbone_completeness: dict[str, Any] | None,
) -> dict[str, Any]:
    wi = warehouse_intelligence if isinstance(warehouse_intelligence, dict) else {}
    kp = competitive_kpis if isinstance(competitive_kpis, dict) else {}
    bb = backbone_completeness if isinstance(backbone_completeness, dict) else {}
    oa = order_analysis if isinstance(order_analysis, dict) else {}

    fe = wi.get("fulfillment_economics") if isinstance(wi.get("fulfillment_economics"), dict) else {}
    cap = wi.get("capacity_baseline") if isinstance(wi.get("capacity_baseline"), dict) else {}
    cna = wi.get("complementary_network_audit") if isinstance(wi.get("complementary_network_audit"), dict) else {}
    events = wi.get("fulfillment_estimate") if isinstance(wi.get("fulfillment_estimate"), dict) else {}

    ingestion_note = (
        "Canonical fields are filled from your CSV column mapping (templates + optional NIM/heuristic infer). "
        "Missing WMS columns → metrics show unavailable/partial; the audit and AI still run on what arrived."
    )

    feed_specs: dict[str, dict[str, Any]] = {
        "labels": {
            "row_count": len(labels),
            "canonical_keys": [
                "dest_postal",
                "origin_postal",
                "weight_lb",
                "carrier",
                "service_code",
                "ship_date",
                "sku",
                "tracking_number",
                "label_amount_usd",
            ],
        },
        "tasks": {
            "row_count": len(tasks),
            "canonical_keys": ["completed_at", "zone", "sku", "operator_id", "task_type", "duration_sec"],
        },
        "order_lines": {
            "row_count": len(order_lines),
            "canonical_keys": [
                "order_external_id",
                "sku",
                "shipped_at_iso",
                "ordered_at_iso",
                "ship_to_postal",
                "channel",
            ],
        },
        "billing_lines": {
            "row_count": len(billing_rows),
            "canonical_keys": ["invoice_id", "amount_usd", "fee_code", "service_start_iso", "service_end_iso"],
        },
        "order_financials": {
            "row_count": len(order_financials),
            "canonical_keys": ["order_external_id", "sku", "revenue_usd", "profit_usd", "ship_to_postal", "order_date_iso"],
        },
        "asn": {"row_count": len(asn_rows), "canonical_keys": ["asn_line_id", "sku", "received_at_iso", "qty_received"]},
        "employees": {"row_count": len(employee_rows), "canonical_keys": ["employee_id", "role", "hourly_rate_usd", "hire_date_iso"]},
    }

    feed_coverage: dict[str, Any] = {}
    for name, spec in feed_specs.items():
        rows = {
            "labels": labels,
            "tasks": tasks,
            "order_lines": order_lines,
            "billing_lines": billing_rows,
            "order_financials": order_financials,
            "asn": asn_rows,
            "employees": employee_rows,
        }[name]
        keys = spec["canonical_keys"]
        cov = _feed_keys(rows, keys)
        min_cov = min(cov.values()) if cov else 0.0
        feed_coverage[name] = {
            "row_count": spec["row_count"],
            "key_fill_rates": cov,
            "weakest_key": min(cov, key=cov.get) if cov else None,
            "weakest_fill_rate": min_cov,
            "status": "absent" if spec["row_count"] == 0 else ("strong" if min_cov >= 0.65 else "partial"),
        }

    g = grain.model_dump()
    temporal: dict[str, Any] = {
        "feeds": {
            fam: {"date_min": (g.get(fam) or {}).get("date_min"), "date_max": (g.get(fam) or {}).get("date_max")}
            for fam in (
                "labels",
                "tasks",
                "order_financials",
                "asn",
                "order_lines",
                "billing",
                "employees",
            )
        },
        "note": "Cross-feed alignment is best-effort when date columns are sparse or different semantics (invoice period vs ship date).",
    }

    join_quality: dict[str, Any] = {
        "grain_join_safety": (g.get("join_safety") or {}),
        "label_order_line_sku_overlap_pct": _sku_overlap_pct(labels, order_lines),
        "label_order_financial_sku_overlap_pct": _sku_overlap_pct(labels, order_financials),
    }

    n_syn = int(g.get("synthetic_task_count") or 0)
    n_tasks = len(tasks)
    syn_pct = round(100.0 * n_syn / n_tasks, 2) if n_tasks else None
    labor_realism = {
        "synthetic_task_row_pct": syn_pct,
        "task_zone_fill_rate": _nonempty_frac(tasks, "zone") if tasks else None,
        "task_operator_fill_rate": _nonempty_frac(tasks, "operator_id") if tasks else None,
        "task_duration_sec_fill_rate": _nonempty_frac(tasks, "duration_sec") if tasks else None,
        "task_completed_at_fill_rate": _nonempty_frac(tasks, "completed_at") if tasks else None,
        "note": "High synthetic % or missing timestamps limits labor efficiency sharpness — upload WMS tasks when possible.",
    }

    fee_fill = _nonempty_frac(billing_rows, "fee_code") if billing_rows else 0.0
    bc = wi.get("billing_components_usd") if isinstance(wi.get("billing_components_usd"), dict) else {}
    bill_total = float(wi.get("billing_usd_total") or 0)
    unknown_usd = float(bc.get("unknown_usd") or 0)
    unknown_share = round(100.0 * unknown_usd / bill_total, 2) if bill_total > 0 else None

    billing_metrics: dict[str, Any] = {
        "fee_code_fill_rate": round(fee_fill, 4) if billing_rows else None,
        "unknown_fee_bucket_share_of_billed_pct": unknown_share,
        "fixed_like_share_of_billed_pct": kp.get("billing_fixed_share_of_total_pct"),
        "variable_ops_share_of_billed_pct": kp.get("billing_variable_ops_share_of_total_pct"),
    }

    naive = fe.get("naive_total_billing_per_fulfillment_event_usd")
    var_ops = fe.get("variable_ops_per_fulfillment_event_usd")
    disc: dict[str, Any]
    try:
        n_f = float(naive) if naive is not None else None
        v_f = float(var_ops) if var_ops is not None else None
    except (TypeError, ValueError):
        n_f = v_f = None
    if n_f is not None and v_f is not None and v_f > 0:
        disc = _m(
            status="complete",
            value=round(n_f / v_f, 3),
            unit="ratio",
            methodology="naive_total_billing_per_fulfillment_event_usd ÷ variable_ops_per_fulfillment_event_usd",
            notes=["High ratio implies headline $/line is dominated by fixed/period charges mixed into the same denominator."],
        )
    elif events.get("fulfillment_events_estimate") and bill_total > 0:
        disc = _m(
            status="partial",
            missing_fields=["fulfillment_economics.variable_ops_per_fulfillment_event_usd or naive pair"],
            notes=["Map fee_code (or GL) into variable vs fixed buckets to unlock discrepancy index."],
        )
    else:
        disc = _m(
            status="unavailable",
            missing_fields=["billing lines + fulfillment event anchor"],
            notes=["Upload billing + labels or shipped order lines."],
        )

    labor_efficiency = _labor_efficiency_metric(cap, n_tasks)

    parcel_readiness = {
        "origin_postal_fill_rate": _nonempty_frac(labels, "origin_postal") if labels else None,
        "dest_postal_fill_rate": _nonempty_frac(labels, "dest_postal") if labels else None,
        "weight_lb_fill_rate": _nonempty_frac(labels, "weight_lb") if labels else None,
        "carrier_fill_rate": _nonempty_frac(labels, "carrier") if labels else None,
        "service_code_fill_rate": _nonempty_frac(labels, "service_code") if labels else None,
    }

    network_metrics = _network_metrics(cna)

    commercial = _commercial_metrics(oa)

    backbone_gaps = len(bb.get("missing") or []) if isinstance(bb.get("missing"), list) else 0

    readiness_scores: list[float | None] = [
        _nonempty_frac(labels, "dest_postal") if labels else None,
        _nonempty_frac(billing_rows, "amount_usd") if billing_rows else None,
        fee_fill if billing_rows else None,
        (1.0 - min(1.0, (syn_pct or 0) / 100.0)) if n_tasks else None,
        _nonempty_frac(order_lines, "ship_to_postal") if order_lines else _nonempty_frac(order_financials, "ship_to_postal"),
    ]
    tier, score = _tier_from_scores(readiness_scores)

    return {
        "schema_version": "audit_sharpness_metrics_v1",
        "ingestion_flex": {
            "message": ingestion_note,
            "canonical_model": "Facts normalize into Cortex label_facts, task_facts, order_line_facts, billing_line_facts, etc.; optional keys stay null.",
        },
        "feed_coverage": feed_coverage,
        "temporal_alignment": temporal,
        "join_quality": join_quality,
        "labor_realism": labor_realism,
        "labor_efficiency": labor_efficiency,
        "billing_clarity": billing_metrics,
        "billing_discrepancy_index": disc,
        "parcel_and_carrier_readiness": parcel_readiness,
        "network_optimization": network_metrics,
        "commercial_snapshot": commercial,
        "backbone_gap_count": backbone_gaps,
        "overall_readiness": {
            "tier": tier,
            "score_0_1": score,
            "drivers": [
                "label_dest_and_billing_amount",
                "fee_code_mapping",
                "real_vs_synthetic_tasks",
                "order_destination_postal",
            ],
        },
    }


def _sku_overlap_pct(a: list[dict], b: list[dict]) -> float | None:
    if not a or not b:
        return None
    sa = {str(r.get("sku") or "").strip() for r in a if r.get("sku")}
    sb = {str(r.get("sku") or "").strip() for r in b if r.get("sku")}
    if not sa or not sb:
        return None
    inter = len(sa & sb)
    return round(100.0 * inter / max(1, len(sa | sb)), 2)


def _labor_efficiency_metric(cap: dict[str, Any], n_tasks: int) -> dict[str, Any]:
    if n_tasks == 0:
        return _m(status="unavailable", missing_fields=["task_facts"], notes=["No tasks — throughput vs baseline N/A."])
    ut = cap.get("observed_vs_baseline_throughput_pct")
    tph = cap.get("observed_tasks_per_hour")
    bline = cap.get("baseline_tasks_per_hour_from_headcount")
    if isinstance(ut, (int, float)):
        return _m(
            status="complete",
            value=round(float(ut), 2),
            unit="pct_of_baseline",
            methodology="observed_tasks_per_hour vs baseline_tasks_per_hour_from_headcount (see capacity_baseline.note)",
            notes=[str(cap.get("note") or "")] if cap.get("note") else None,
        )
    if tph is not None:
        return _m(
            status="partial",
            value=round(float(tph), 4),
            unit="tasks_per_hour",
            missing_fields=["observed_vs_baseline_throughput_pct"],
            notes=["Baseline comparison suppressed — often long timestamp span or synthetic tasks."],
        )
    return _m(status="unavailable", missing_fields=["observed_tasks_per_hour"], notes=["Need task timestamps in a usable window."])


def _network_metrics(cna: dict[str, Any]) -> dict[str, Any]:
    if cna.get("status") != "complete":
        msg = cna.get("message") or "complementary_network_audit skipped or incomplete"
        return _m(status="unavailable" if not cna else "partial", notes=[msg])
    try:
        max_dest = 25
        sampled = int(cna.get("lanes_sampled") or 0)
        zip3c = (cna.get("demand_rollup_merged") or {}).get("zip3_count") or 0
        cov = round(100.0 * sampled / max(1, int(zip3c)), 2) if zip3c else None
    except (TypeError, ValueError):
        cov = None
    return {
        "complementary_audit_status": "complete",
        "out_of_region_merged_line_share_pct": cna.get("out_of_region_order_share_pct_all_zip3"),
        "aggregate_delta_usd_per_line_out_of_region": cna.get("aggregate_delta_usd_per_line_out_of_region"),
        "tiered_total_nodes": cna.get("tiered_total_nodes"),
        "quote_sample_coverage": _m(
            status="complete" if cov is not None else "partial",
            value=cov,
            unit="pct_of_zip3s_quoted",
            methodology="lanes_sampled ÷ merged zip3_count (capped quotes; see complementary_network_audit.limitations)",
        ),
    }


def _commercial_metrics(oa: dict[str, Any]) -> dict[str, Any]:
    if not oa or not oa.get("row_count"):
        return _m(status="unavailable", missing_fields=["order_financial_facts"], notes=["Upload order_financials for margin-style reads."])
    totals = oa.get("totals") if isinstance(oa.get("totals"), dict) else {}
    ffi = oa.get("full_financial_image") if isinstance(oa.get("full_financial_image"), dict) else {}
    margin = ffi.get("csv_reported_net_margin_pct")
    if margin is None and totals.get("revenue_usd") and totals.get("profit_usd"):
        try:
            r, p = float(totals["revenue_usd"]), float(totals["profit_usd"])
            margin = round(100.0 * p / r, 4) if r else None
        except (TypeError, ValueError):
            margin = None
    rev = totals.get("revenue_usd")
    return {
        "order_financial_rows": oa.get("row_count"),
        "seller_net_margin_pct": margin,
        "seller_revenue_usd_total": rev,
        "status": "complete" if margin is not None else "partial",
        "reference_handle_usd_for_context": REFERENCE_TYPICAL_ORDER_HANDLE_USD,
    }

"""Deterministic competitive / profitability KPIs from backbone facts (no LLM)."""

from __future__ import annotations

from typing import Any

from unie_cortex.services.audit_contracts import AuditGrainReport
from unie_cortex.services.warehouse_intelligence_baseline import REFERENCE_TYPICAL_ORDER_HANDLE_USD


def build_competitive_kpis(
    *,
    grain: AuditGrainReport,
    warehouse_intelligence: dict[str, Any] | None,
    order_analysis: dict[str, Any] | None,
) -> dict[str, Any]:
    wi = warehouse_intelligence if isinstance(warehouse_intelligence, dict) else {}
    oa = order_analysis if isinstance(order_analysis, dict) else {}

    bc = wi.get("billing_components_usd") if isinstance(wi.get("billing_components_usd"), dict) else {}
    fixed = float(bc.get("fixed_like_usd") or 0)
    var_ops = float(bc.get("variable_ops_usd") or 0)
    unknown = float(bc.get("unknown_usd") or 0)
    bill_total = float(wi.get("billing_usd_total") or 0)

    fixed_share_pct = round(100.0 * fixed / bill_total, 2) if bill_total > 0 else None
    variable_share_pct = round(100.0 * var_ops / bill_total, 2) if bill_total > 0 else None

    fe = wi.get("fulfillment_economics") if isinstance(wi.get("fulfillment_economics"), dict) else {}
    est_handle = fe.get("estimated_cost_per_fulfillment_usd")
    naive = fe.get("naive_total_billing_per_fulfillment_event_usd")
    try:
        est_f = float(est_handle) if est_handle is not None else None
    except (TypeError, ValueError):
        est_f = None
    handle_vs_reference_ratio = round(est_f / REFERENCE_TYPICAL_ORDER_HANDLE_USD, 4) if est_f and REFERENCE_TYPICAL_ORDER_HANDLE_USD else None

    vb = wi.get("volume_baseline") if isinstance(wi.get("volume_baseline"), dict) else {}
    channel_mix = vb.get("channel_mix_top") if isinstance(vb.get("channel_mix_top"), dict) else {}
    headcount = wi.get("headcount_used")
    opm = vb.get("orders_per_month_estimate")
    orders_per_fte_month: float | None = None
    if opm is not None and headcount is not None:
        try:
            o, h = float(opm), float(headcount)
            orders_per_fte_month = round(o / h, 4) if h > 0 else None
        except (TypeError, ValueError):
            orders_per_fte_month = None

    totals = oa.get("totals") if isinstance(oa.get("totals"), dict) else {}
    revenue = totals.get("revenue_usd")
    profit = totals.get("profit_usd")
    ffi = oa.get("full_financial_image") if isinstance(oa.get("full_financial_image"), dict) else {}
    margin_pct = ffi.get("csv_reported_net_margin_pct")
    gross_margin_pct = ffi.get("gross_margin_pct")
    if margin_pct is None and revenue is not None and profit is not None:
        try:
            r, p = float(revenue), float(profit)
            margin_pct = round(100.0 * p / r, 4) if r else None
        except (TypeError, ValueError):
            margin_pct = None

    inbound_outbound_ratio = None
    if grain.asn.row_count > 0 and grain.order_lines.row_count > 0:
        inbound_outbound_ratio = round(grain.asn.row_count / grain.order_lines.row_count, 4)

    return {
        "schema_version": "warehouse_competitive_kpis_v1",
        "billing_fixed_share_of_total_pct": fixed_share_pct,
        "billing_variable_ops_share_of_total_pct": variable_share_pct,
        "billing_unknown_share_of_total_pct": round(100.0 * unknown / bill_total, 2) if bill_total > 0 else None,
        "estimated_handle_usd": est_f,
        "naive_total_per_line_usd": float(naive) if naive is not None else None,
        "handle_to_reference_typical_ratio": handle_vs_reference_ratio,
        "reference_typical_handle_usd": REFERENCE_TYPICAL_ORDER_HANDLE_USD,
        "orders_per_month_estimate": vb.get("orders_per_month_estimate"),
        "orders_per_fte_month_estimate": orders_per_fte_month,
        "headcount_used": headcount,
        "distinct_orders_in_window": vb.get("distinct_orders_in_window"),
        "channel_mix_top": channel_mix,
        "inbound_asn_lines": grain.asn.row_count,
        "outbound_order_lines": grain.order_lines.row_count,
        "inbound_to_outbound_line_ratio": inbound_outbound_ratio,
        "order_financials_row_count": grain.order_financials.row_count,
        "seller_revenue_usd_total": totals.get("revenue_usd"),
        "seller_profit_usd_total": totals.get("profit_usd"),
        "seller_net_margin_pct": margin_pct,
        "seller_gross_margin_pct": gross_margin_pct,
        "order_analysis_row_count": oa.get("row_count"),
    }

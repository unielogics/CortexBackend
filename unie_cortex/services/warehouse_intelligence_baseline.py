"""Baseline capacity and fulfillment economics from facility, location, employees, billing, and orders."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any

# Typical pick/pack handle (excludes parcel) — anchor for spotting naive billing/line inflation.
REFERENCE_TYPICAL_ORDER_HANDLE_USD = 3.0

# Mid-range pick/put equivalents per productive labor hour (planning constant; tune with benchmarks).
_DEFAULT_TASKS_PER_PRODUCTIVE_HOUR = 25.0
_PRODUCTIVE_HOURS_PER_FTE_DAY = 6.5
# If task min/max span exceeds this, do not infer tasks/hour from wall-clock spread (common with synthetic rows).
_MAX_HOURS_FOR_THROUGHPUT_FROM_TIMESTAMP_SPAN = 336.0  # 14 days

# Above this naive ratio (billing_total/events vs typical handle), treat headline $/order as misleading when fee codes imply fixed/period mix.
_NAIVE_PER_EVENT_IMPLAUSIBLE_VS_REFERENCE = 10.0


def _parse_task_ts(s: str | None) -> datetime | None:
    if not s or not str(s).strip():
        return None
    t = str(s).strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(t)
    except ValueError:
        return None


def _parse_ship_ts(s: str | None) -> datetime | None:
    return _parse_task_ts(s)


def _task_observation_window_hours(tasks: list[dict[str, Any]]) -> float | None:
    parsed: list[datetime] = []
    for row in tasks:
        dt = _parse_task_ts(row.get("completed_at"))
        if dt:
            parsed.append(dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt)
    if len(parsed) < 2:
        return None
    parsed.sort()
    span = (parsed[-1] - parsed[0]).total_seconds() / 3600.0
    return span if span > 1e-6 else None


def estimate_fulfillment_events(
    *,
    labels: list[dict[str, Any]],
    order_lines: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Proxy for outbound / handling events in the assessment window.
    Uses max(labels, shipped order lines) so either feed can anchor the denominator.
    Prefer distinct order count in economics (see volume_baseline); events here stay line-oriented for throughput.
    """
    n_labels = len(labels)
    shipped = [r for r in order_lines if (r.get("shipped_at_iso") or "").strip()]
    n_shipped_lines = len(shipped)
    n_orders = len({r.get("order_external_id") for r in shipped if r.get("order_external_id")})

    events = max(n_labels, n_shipped_lines, 1)
    return {
        "fulfillment_events_estimate": events,
        "components": {
            "label_rows": n_labels,
            "order_lines_shipped": n_shipped_lines,
            "distinct_orders_shipped": n_orders,
        },
        "methodology": "max(label_rows, order_lines_with_shipped_at); min 1 to avoid divide-by-zero",
    }


def _billing_total_usd(rows: list[dict[str, Any]]) -> float:
    s = 0.0
    for r in rows:
        v = r.get("amount_usd")
        if v is None:
            continue
        try:
            s += float(v)
        except (TypeError, ValueError):
            continue
    return s


def _fee_bucket(fee_code: str | None) -> str:
    """Classify invoice line for per-order economics vs period overhead."""
    u = (fee_code or "").upper()
    if not u.strip():
        return "unknown"
    if any(t in u for t in ("RENT", "LEASE", "CAM", "INSUR", "OVERHEAD", "MINIMUM", "MINS ", "MGMT", "ADMIN")):
        return "fixed_period"
    if "LABOR" in u and "ORDER" not in u and "PICK" not in u:
        return "labor_block"
    if any(
        t in u
        for t in (
            "PICK",
            "PACK",
            "PER_ORDER",
            "HANDLE",
            "FBM",
            "FBA_PREP",
            "PREP",
            "OUTBOUND",
            "SHIP",
            "CARTON",
            "PALLET_OUT",
            "UNIT",
        )
    ):
        return "variable_ops"
    return "unknown"


def _billing_split(billing_rows: list[dict[str, Any]]) -> dict[str, Any]:
    fixed_like = 0.0
    variable_ops = 0.0
    unknown = 0.0
    by_code: dict[str, float] = {}
    for r in billing_rows:
        amt = r.get("amount_usd")
        try:
            a = float(amt) if amt is not None else 0.0
        except (TypeError, ValueError):
            continue
        code = str(r.get("fee_code") or "").strip()
        if code:
            by_code[code] = by_code.get(code, 0.0) + a
        b = _fee_bucket(code if code else None)
        if b == "variable_ops":
            variable_ops += a
        elif b in ("fixed_period", "labor_block"):
            fixed_like += a
        else:
            unknown += a
    return {
        "fixed_like_usd": round(fixed_like, 2),
        "variable_ops_usd": round(variable_ops, 2),
        "unknown_usd": round(unknown, 2),
        "by_fee_code_usd": {k: round(v, 2) for k, v in sorted(by_code.items(), key=lambda x: -x[1])[:25]},
    }


def _volume_baseline_from_orders(order_lines: list[dict[str, Any]]) -> dict[str, Any]:
    shipped = [r for r in order_lines if (r.get("shipped_at_iso") or "").strip()]
    order_ids = [r.get("order_external_id") for r in shipped if r.get("order_external_id")]
    distinct_orders = len(set(order_ids))
    months_counter: Counter[str] = Counter()
    for r in shipped:
        dt = _parse_ship_ts(r.get("shipped_at_iso"))
        if dt:
            months_counter[dt.strftime("%Y-%m")] += 1
    n_months = len(months_counter)
    if shipped:
        dates = [d for r in shipped if (d := _parse_ship_ts(r.get("shipped_at_iso")))]
        if len(dates) >= 2:
            dates.sort()
            span_days = max(1.0, (dates[-1] - dates[0]).days + 1)
            months_frac = max(span_days / 30.44, n_months or 1.0)
        else:
            months_frac = max(n_months, 1.0)
    else:
        months_frac = 1.0

    orders_per_month = round(distinct_orders / months_frac, 2) if distinct_orders else None
    channel_mix = Counter((str(r.get("channel") or "").strip().upper() or "UNKNOWN") for r in shipped)

    return {
        "distinct_orders_in_window": distinct_orders,
        "shipped_order_lines_in_window": len(shipped),
        "months_with_ship_activity": n_months,
        "months_in_window_fractional": round(months_frac, 2),
        "orders_per_month_estimate": orders_per_month,
        "channel_mix_top": dict(channel_mix.most_common(6)),
    }


def _labor_baseline_from_employees(employee_rows: list[dict[str, Any]], headcount: int | None) -> dict[str, Any]:
    rates: list[float] = []
    for r in employee_rows:
        v = r.get("hourly_rate_usd")
        if v is None:
            continue
        try:
            rates.append(float(v))
        except (TypeError, ValueError):
            continue
    avg = round(sum(rates) / len(rates), 4) if rates else None
    fte = float(headcount) if headcount and headcount > 0 else float(len(employee_rows) or 0)
    implied_monthly = None
    if avg is not None and fte > 0:
        # Order-of-magnitude: FTE × 40 h/wk × ~4.33 wk/mo × avg hourly (not loaded OT / benefits).
        implied_monthly = round(avg * fte * 40.0 * 4.33, 2)
    return {
        "employee_rows_used": len(employee_rows),
        "avg_hourly_rate_usd": avg,
        "implied_monthly_labor_usd_order_of_magnitude": implied_monthly,
        "note": "Implied monthly labor is a rough order-of-magnitude from avg rate × headcount × hours; not payroll truth.",
    }


def _location_from_network(network_context: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(network_context, dict):
        return {}
    whs = network_context.get("candidate_warehouses")
    if not isinstance(whs, list) or not whs:
        return {}
    w0 = whs[0]
    if not isinstance(w0, dict):
        return {}
    return {
        "primary_ship_from_postal": (str(w0.get("postal")).strip() if w0.get("postal") else None),
        "primary_warehouse_label": w0.get("label") or w0.get("id") or w0.get("name"),
    }


def build_warehouse_intelligence_baseline(
    *,
    facility_profile: dict[str, Any] | None,
    labels: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    asn_rows: list[dict[str, Any]],
    order_lines: list[dict[str, Any]],
    billing_rows: list[dict[str, Any]],
    employee_rows: list[dict[str, Any]],
    network_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fp = dict(facility_profile) if isinstance(facility_profile, dict) else {}
    nc = network_context if isinstance(network_context, dict) else None
    synthetic_fill: list[str] = []

    sqft = fp.get("sqft")
    try:
        sqft_f = float(sqft) if sqft is not None else None
    except (TypeError, ValueError):
        sqft_f = None

    loading_dock = fp.get("loading_dock")
    if loading_dock is not None and not isinstance(loading_dock, bool):
        loading_dock = bool(loading_dock)

    truck_recv = fp.get("truck_receive_capabilities")
    if truck_recv is not None:
        truck_recv = str(truck_recv)[:2000]

    headcount: int | None = None
    head_src: str | None = None
    hr = fp.get("headcount_reported")
    if hr is not None:
        try:
            headcount = int(hr)
            if headcount >= 0:
                head_src = "facility_profile"
        except (TypeError, ValueError):
            headcount = None
    if headcount is None and employee_rows:
        headcount = len(employee_rows)
        head_src = "employee_roster_row_count"
        synthetic_fill.append(
            "headcount_reported missing — using employee roster row count as FTE proxy (low precision)."
        )

    loc = _location_from_network(nc)
    if not loc.get("primary_ship_from_postal"):
        synthetic_fill.append(
            "Set candidate_warehouses[].postal in network-context so regional and rate-shop logic anchor to your ship-from ZIP."
        )

    fe = estimate_fulfillment_events(labels=labels, order_lines=order_lines)
    events = int(fe["fulfillment_events_estimate"])
    billing_total = _billing_total_usd(billing_rows)
    split = _billing_split(billing_rows)
    has_fee_codes = any((r.get("fee_code") or "").strip() for r in billing_rows)

    naive_per_event: float | None = None
    if billing_total > 0 and events > 0:
        naive_per_event = round(billing_total / events, 4)

    var_total = float(split["variable_ops_usd"])
    variable_per_event: float | None = None
    if var_total > 0 and events > 0:
        variable_per_event = round(var_total / events, 4)

    implausible = False
    warnings: list[str] = []
    if naive_per_event is not None:
        ratio = naive_per_event / REFERENCE_TYPICAL_ORDER_HANDLE_USD
        if ratio >= _NAIVE_PER_EVENT_IMPLAUSIBLE_VS_REFERENCE:
            implausible = True
            warnings.append(
                f"Total billing ÷ shipment lines (~${naive_per_event:,.2f}/line) is far above a typical ~${REFERENCE_TYPICAL_ORDER_HANDLE_USD:.0f} "
                "pick/pack handle — invoices usually include rent, labor blocks, prep, and multi-order periods. Do not read this as per-order fulfillment cost."
            )
    if has_fee_codes and split["fixed_like_usd"] > split["variable_ops_usd"] and naive_per_event:
        warnings.append(
            "Fixed or period-style fee codes (e.g. rent, labor blocks) dominate variable pick/pack lines — use variable_ops_usd ÷ orders for handle economics."
        )

    # Headline field: prefer variable ops per event; avoid publishing misleading naive when fee mix explains inflation.
    cost_per_fulfillment: float | None = None
    if variable_per_event is not None:
        cost_per_fulfillment = variable_per_event
    elif naive_per_event is not None:
        if has_fee_codes and implausible:
            cost_per_fulfillment = None
        elif not has_fee_codes:
            cost_per_fulfillment = naive_per_event
        elif implausible:
            cost_per_fulfillment = None
        else:
            cost_per_fulfillment = naive_per_event

    if billing_total <= 0:
        synthetic_fill.append("No billing amounts — cannot estimate cost per fulfillment from invoices.")
        if events > 0:
            synthetic_fill.append("Upload billing CSV with amount_usd to anchor cost-per-fulfillment.")

    fulfillment_economics: dict[str, Any] = {
        "schema_version": "fulfillment_economics_v1",
        "reference_typical_order_handle_usd": REFERENCE_TYPICAL_ORDER_HANDLE_USD,
        "naive_total_billing_per_fulfillment_event_usd": naive_per_event,
        "variable_ops_per_fulfillment_event_usd": variable_per_event,
        "estimated_cost_per_fulfillment_usd": cost_per_fulfillment,
        "naive_per_event_implausible_vs_reference": implausible,
        "interpretation_warnings": warnings,
        "interpretation_summary": (
            "Variable pick/pack / per-order lines divided by shipped lines — best available per-order ops read."
            if variable_per_event is not None
            else (
                "No variable_ops fee lines detected — total billing mixes fixed and period charges; see warnings."
                if has_fee_codes and billing_total > 0
                else "Map fee_code on billing lines to separate fixed rent/labor from per-order handles."
            )
        ),
    }

    baseline_tasks_per_hour: float | None = None
    if headcount is not None and headcount > 0:
        baseline_tasks_per_hour = float(headcount) * _DEFAULT_TASKS_PER_PRODUCTIVE_HOUR
        if loading_dock is True:
            baseline_tasks_per_hour *= 1.05
    else:
        synthetic_fill.append("No headcount — baseline tasks/hour not computed.")

    window_h = _task_observation_window_hours(tasks)
    observed_tph: float | None = None
    utilization_pct: float | None = None
    if window_h and len(tasks) > 0:
        if window_h > _MAX_HOURS_FOR_THROUGHPUT_FROM_TIMESTAMP_SPAN:
            synthetic_fill.append(
                "Task timestamps span a long calendar range — observed_tasks_per_hour vs baseline suppressed; "
                "pass reporting_period_hours or dense task export for utilization."
            )
        else:
            observed_tph = round(len(tasks) / window_h, 4)
            if baseline_tasks_per_hour and baseline_tasks_per_hour > 0:
                utilization_pct = round(100.0 * observed_tph / baseline_tasks_per_hour, 2)

    synthetic_n = sum(
        1
        for t in tasks
        if isinstance(t.get("extra"), dict) and (t.get("extra") or {}).get("provenance") == "synthetic"
    )

    volume_baseline = _volume_baseline_from_orders(order_lines)
    labor_baseline = _labor_baseline_from_employees(employee_rows, headcount)

    return {
        "schema_version": "warehouse_intelligence_v2",
        "reference_typical_order_handle_usd": REFERENCE_TYPICAL_ORDER_HANDLE_USD,
        "location_context": {
            **loc,
            "sqft": sqft_f,
            "loading_dock": loading_dock,
            "truck_receive_capabilities": truck_recv,
            "headcount_reported": fp.get("headcount_reported"),
        },
        "facility_profile": {
            k: v
            for k, v in {
                "sqft": sqft_f,
                "loading_dock": loading_dock,
                "truck_receive_capabilities": truck_recv,
                "headcount_reported": fp.get("headcount_reported"),
            }.items()
            if v is not None
        },
        "headcount_used": headcount,
        "headcount_source": head_src,
        "inbound_activity_rows": len(asn_rows),
        "fulfillment_estimate": fe,
        "billing_usd_total": round(billing_total, 2),
        "billing_components_usd": {
            "fixed_like_usd": split["fixed_like_usd"],
            "variable_ops_usd": split["variable_ops_usd"],
            "unknown_usd": split["unknown_usd"],
            "by_fee_code_usd": split["by_fee_code_usd"],
        },
        "volume_baseline": volume_baseline,
        "labor_baseline": labor_baseline,
        "fulfillment_economics": fulfillment_economics,
        # Back-compat: same as fulfillment_economics.estimated_cost_per_fulfillment_usd
        "estimated_cost_per_fulfillment_usd": cost_per_fulfillment,
        "capacity_baseline": {
            "tasks_per_productive_hour_assumption": _DEFAULT_TASKS_PER_PRODUCTIVE_HOUR,
            "productive_hours_per_fte_day_assumption": _PRODUCTIVE_HOURS_PER_FTE_DAY,
            "baseline_tasks_per_hour_from_headcount": round(baseline_tasks_per_hour, 2)
            if baseline_tasks_per_hour
            else None,
            "observed_task_rows": len(tasks),
            "synthetic_task_rows": synthetic_n,
            "observation_window_hours": round(window_h, 4) if window_h else None,
            "observed_tasks_per_hour": observed_tph,
            "observed_vs_baseline_throughput_pct": utilization_pct,
            "note": "Baseline is a planning anchor for optimization deltas (efficiency, tasks/min, hours), not a labor standard.",
        },
        "synthetic_fill": synthetic_fill,
        "confidence": "medium"
        if (billing_total > 0 and headcount is not None)
        else ("low" if billing_total > 0 or headcount is not None else "minimal"),
    }

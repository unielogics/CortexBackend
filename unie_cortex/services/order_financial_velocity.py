"""
Velocity and simple month-completion signals from order-financial rows only (no Keepa).

Assumptions: order_date_iso parseable; quantity defaults to 1 when missing.
Forecast is heuristic (trailing run-rate × days remaining in month)—not statistical ML.
"""

from __future__ import annotations

import re
from calendar import monthrange
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any


def _parse_order_datetime(raw: str | None) -> datetime | None:
    if not raw:
        return None
    s = str(raw).strip()
    if not s:
        return None

    # Fast-path for ISO 8601-like formats
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        try:
            if "T" in s:
                # 2024-01-01T12:00:00Z or 2024-01-01T12:00:00.000Z
                dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            else:
                # 2024-01-01 or 2024-01-01 12:00:00
                dt = datetime.fromisoformat(s)

            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            pass

    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%d/%m/%Y",
    ):
        try:
            dt = datetime.strptime(s[:26], fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", s)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def _qty(row: dict[str, Any]) -> float:
    try:
        q = float(row.get("quantity") or 0)
        return q if q > 0 else 1.0
    except (TypeError, ValueError):
        return 1.0


def order_financial_line_group_key(row: dict[str, Any]) -> str:
    sku = (row.get("sku") or "").strip()
    if sku:
        return f"sku:{sku}"
    asin = (row.get("asin") or "").strip()
    if asin:
        return f"asin:{asin.upper()}"
    return "unknown"


@dataclass
class _Line:
    dt: datetime
    units: float
    order_id: str | None


def _order_date_raw(row: dict[str, Any]) -> str | None:
    v = row.get("order_date_iso") or row.get("order_date")
    return str(v).strip() if v not in (None, "") else None


def _lines_for_group(rows: list[dict[str, Any]]) -> list[_Line]:
    out: list[_Line] = []
    for row in rows:
        dt = _parse_order_datetime(_order_date_raw(row))
        if dt is None:
            continue
        out.append(
            _Line(
                dt=dt,
                units=_qty(row),
                order_id=(row.get("order_external_id") or row.get("order_id")),
            )
        )
    out.sort(key=lambda x: x.dt)
    return out


def _max_gap_days(sorted_dts: list[datetime]) -> int | None:
    if len(sorted_dts) < 2:
        return None
    mx = 0
    for a, b in zip(sorted_dts, sorted_dts[1:]):
        d = (b.date() - a.date()).days
        if d > mx:
            mx = d
    return mx


def _units_in_window(lines: list[_Line], end: date, days: int) -> float:
    start = end - timedelta(days=days - 1)
    s = 0.0
    for ln in lines:
        d = ln.dt.date()
        if start <= d <= end:
            s += ln.units
    return s


def analyze_velocity_group(
    rows: list[dict[str, Any]],
    *,
    group_key: str,
    trailing_days_short: int = 30,
    trailing_days_long: int = 60,
) -> dict[str, Any]:
    lines = _lines_for_group(rows)
    if not lines:
        return {
            "group_key": group_key,
            "status": "no_parseable_dates",
            "line_count": len(rows),
        }

    dts = [ln.dt for ln in lines]
    last_dt = dts[-1]
    last_date = last_dt.date()
    first_date = dts[0].date()

    by_month: dict[str, float] = defaultdict(float)
    active_days: set[date] = set()
    for ln in lines:
        k = f"{ln.dt.year:04d}-{ln.dt.month:02d}"
        by_month[k] += ln.units
        active_days.add(ln.dt.date())

    sorted_month_keys = sorted(by_month.keys())
    max_gap = _max_gap_days(dts)

    end_tr = last_date
    trail_short = _units_in_window(lines, end_tr, trailing_days_short)
    trail_long = _units_in_window(lines, end_tr, trailing_days_long)
    # run-rate: units per day over short window (min 1 day span)
    span_short = min(trailing_days_short, (last_date - first_date).days + 1) or 1
    units_per_day_short = trail_short / float(max(1, min(span_short, trailing_days_short)))

    # Month completion forecast (calendar month of last order)
    y, m = last_date.year, last_date.month
    _, dim = monthrange(y, m)
    month_start = date(y, m, 1)
    month_end = date(y, m, dim)
    sold_mtd = sum(ln.units for ln in lines if ln.dt.date().month == m and ln.dt.date().year == y)
    days_elapsed = (last_date - month_start).days + 1
    days_left = max(0, (month_end - last_date).days)
    forecast_rest_of_month = units_per_day_short * float(days_left)
    forecast_month_end_units = round(sold_mtd + forecast_rest_of_month, 2)

    sparse = len(lines) < 5 or span_short < 7

    return {
        "group_key": group_key,
        "status": "complete",
        "order_lines_used": len(lines),
        "first_order_date": first_date.isoformat(),
        "last_order_date": last_date.isoformat(),
        "active_distinct_days": len(active_days),
        "calendar_months_with_orders": len(by_month),
        "units_by_month": {k: round(by_month[k], 4) for k in sorted_month_keys},
        "max_gap_days_between_orders": max_gap,
        f"trailing_{trailing_days_short}d_units": round(trail_short, 4),
        f"trailing_{trailing_days_long}d_units": round(trail_long, 4),
        "estimated_units_per_day_trailing_short": round(units_per_day_short, 6),
        "month_in_progress": {
            "calendar_month": f"{y:04d}-{m:02d}",
            "month_to_date_units": round(sold_mtd, 4),
            "days_elapsed_in_month_through_last_order": days_elapsed,
            "days_remaining_in_month_after_last_order": days_left,
            "synthetic_forecast_units_rest_of_month": round(forecast_rest_of_month, 2),
            "synthetic_forecast_month_end_total_units": forecast_month_end_units,
        },
        "sparse_history": sparse,
        "method_note": "Trailing run-rate forecast; not Keepa. Use sparse_history before trusting forecast.",
    }


def build_batch_velocity_enrichment(
    canonical_rows: list[dict[str, Any]],
    *,
    trailing_days_short: int = 30,
    trailing_days_long: int = 60,
) -> dict[str, Any]:
    """
    One pass: per-SKU/ASIN velocity + batch-level monthly totals for network gates.
    """
    by_g: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in canonical_rows:
        by_g[order_financial_line_group_key(row)].append(row)

    by_group: dict[str, Any] = {}
    for gk, grows in by_g.items():
        by_group[gk] = analyze_velocity_group(
            grows,
            group_key=gk,
            trailing_days_short=trailing_days_short,
            trailing_days_long=trailing_days_long,
        )

    # Batch-wide units by calendar month (all groups)
    all_lines = _lines_for_group(canonical_rows)
    batch_by_month: dict[str, float] = defaultdict(float)
    for ln in all_lines:
        k = f"{ln.dt.year:04d}-{ln.dt.month:02d}"
        batch_by_month[k] += ln.units
    sorted_bm = sorted(batch_by_month.keys())
    peak_month_units = max(batch_by_month.values()) if batch_by_month else 0.0
    last_month_key = sorted_bm[-1] if sorted_bm else None
    last_month_units = batch_by_month[last_month_key] if last_month_key else 0.0

    # Suggested monthly demand for smart_network: prefer peak month, else last month
    estimated_monthly_demand_units = max(peak_month_units, last_month_units, 1.0)

    return {
        "assumptions_version": "order_financial_velocity_v1",
        "trailing_days_short": trailing_days_short,
        "trailing_days_long": trailing_days_long,
        "by_sku_or_asin": by_group,
        "batch_units_by_month": {k: round(batch_by_month[k], 4) for k in sorted_bm},
        "batch_peak_month_units": round(peak_month_units, 4),
        "batch_last_month_key": last_month_key,
        "batch_last_month_units": round(last_month_units, 4),
        "estimated_monthly_demand_units_for_planning": round(estimated_monthly_demand_units, 4),
    }

"""Billing × ASN date-window inference without SKU-level joins."""

from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from typing import Any


def _parse_iso_to_date(raw: str | None) -> date | None:
    if not raw or not str(raw).strip():
        return None
    s = str(raw).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt.date()
    except ValueError:
        pass
    m = s[:10]
    if len(m) >= 10 and m[4] == "-" and m[7] == "-":
        try:
            return datetime.strptime(m[:10], "%Y-%m-%d").date()
        except ValueError:
            pass
    return None


def _billing_interval(row: dict[str, Any]) -> tuple[date, date] | None:
    start = _parse_iso_to_date(row.get("service_start_iso"))
    end = _parse_iso_to_date(row.get("service_end_iso"))
    if start is None and end is None:
        return None
    if start is None:
        start = end  # type: ignore[assignment]
    if end is None:
        assert start is not None
        last = monthrange(start.year, start.month)[1]
        end = date(start.year, start.month, last)
    if end < start:
        end = start
    return (start, end)


def _is_variable_ops_fee(fee_code: str | None) -> bool:
    u = (fee_code or "").upper()
    if not u.strip():
        return False
    if any(t in u for t in ("RENT", "LEASE", "CAM", "INSUR", "OVERHEAD", "MINIMUM", "MINS ", "MGMT", "ADMIN")):
        return False
    if "LABOR" in u and "ORDER" not in u and "PICK" not in u:
        return False
    return any(
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
    )


def _asn_received_date(row: dict[str, Any]) -> date | None:
    return _parse_iso_to_date(row.get("received_at_iso")) or _parse_iso_to_date(row.get("expected_at_iso"))


def _asn_units(row: dict[str, Any]) -> float:
    for k in ("qty_received", "qty_expected", "quantity"):
        v = row.get(k)
        if v is None:
            continue
        try:
            q = float(v)
            if q > 0:
                return q
        except (TypeError, ValueError):
            continue
    return 0.0


def build_period_billing_asn_inference(
    billing_rows: list[dict[str, Any]],
    asn_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Relate variable-ops billing amounts to ASN-received units using calendar overlap only.
    No SKU join — suitable when invoices are period-based and ASN has receipt dates.
    """
    notes: list[str] = []
    if not billing_rows and not asn_rows:
        return {
            "schema_version": "period_billing_asn_inference_v1",
            "status": "skipped",
            "reason": "no_billing_and_no_asn",
            "windows": [],
            "notes": [],
        }
    if not asn_rows:
        return {
            "schema_version": "period_billing_asn_inference_v1",
            "status": "partial",
            "reason": "no_asn_rows",
            "windows": [],
            "notes": ["Add ASN with received_at_iso / qty_received to infer $/unit received against billing periods."],
        }

    # Variable-ops billing lines with intervals
    bill_windows: list[dict[str, Any]] = []
    var_ops_total = 0.0
    for i, row in enumerate(list(billing_rows or [])):
        amt = row.get("amount_usd")
        try:
            a = float(amt) if amt is not None else 0.0
        except (TypeError, ValueError):
            a = 0.0
        if a <= 0:
            continue
        if not _is_variable_ops_fee(row.get("fee_code")):
            continue
        inv = _billing_interval(row)
        if inv is None:
            notes.append(f"billing row {i}: variable_ops amount without parseable service dates — skipped")
            continue
        s, e = inv
        bill_windows.append({"start": s, "end": e, "amount_usd": round(a, 4), "fee_code": row.get("fee_code")})
        var_ops_total += a

    asn_by_day: dict[date, float] = {}
    for row in asn_rows:
        d = _asn_received_date(row)
        if d is None:
            continue
        u = _asn_units(row)
        if u <= 0:
            u = 1.0
        asn_by_day[d] = asn_by_day.get(d, 0.0) + u

    if not bill_windows:
        if var_ops_total == 0 and billing_rows:
            notes.append("No variable_ops billing lines with date range — fee_code may be unknown or fixed-period only.")
        return {
            "schema_version": "period_billing_asn_inference_v1",
            "status": "partial",
            "reason": "no_dated_variable_ops_billing",
            "windows": [],
            "total_variable_ops_usd_considered": round(var_ops_total, 2),
            "asn_units_sum_all_dates": round(sum(asn_by_day.values()), 2),
            "notes": notes,
        }

    windows_out: list[dict[str, Any]] = []
    for bw in bill_windows:
        s, e = bw["start"], bw["end"]
        units = 0.0
        d = s
        while d <= e:
            units += asn_by_day.get(d, 0.0)
            d += timedelta(days=1)
        amt = float(bw["amount_usd"])
        implied = round(amt / max(1.0, units), 6) if units > 0 else None
        windows_out.append(
            {
                "service_start": s.isoformat(),
                "service_end": e.isoformat(),
                "variable_ops_usd": amt,
                "asn_units_received_in_window": round(units, 4),
                "implied_variable_ops_per_received_unit_usd": implied,
                "fee_code": bw.get("fee_code"),
            }
        )

    global_units = sum(asn_by_day.values())
    rollup = round(var_ops_total / max(1.0, global_units), 6) if global_units > 0 else None

    return {
        "schema_version": "period_billing_asn_inference_v1",
        "status": "complete" if windows_out else "partial",
        "windows": windows_out,
        "rollup_variable_ops_usd": round(var_ops_total, 2),
        "rollup_asn_units_all_dated_receipts": round(global_units, 2),
        "rollup_implied_variable_ops_per_received_unit_usd": rollup,
        "notes": notes
        + [
            "Inference uses calendar overlap only (not SKU). Treat as directional when invoices span partial months "
            "or ASN dates are expected vs received."
        ],
    }

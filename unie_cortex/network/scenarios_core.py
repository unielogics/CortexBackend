"""Shared destination normalization for network scenarios."""

from __future__ import annotations

from typing import Any


def normalize_destinations(
    qty: int,
    destinations: list[dict[str, Any]],
) -> tuple[list[tuple[str, int]] | None, dict[str, Any] | None]:
    """
    Returns (list of (postal, units), error_response) — error_response is a small dict
    for API when validation fails.
    """
    if qty <= 0:
        return None, {"status": "skipped", "message": "qty must be positive", "recommendation": "noop"}

    if not destinations:
        return None, {"status": "skipped", "message": "destinations required", "recommendation": "noop"}

    dests: list[tuple[str, int]] = []
    explicit = sum(int(d.get("units") or 0) for d in destinations)
    if explicit == 0:
        posts = [str(d.get("postal") or "").strip() for d in destinations if str(d.get("postal") or "").strip()]
        if not posts:
            return None, {"status": "skipped", "message": "No valid destination postals", "recommendation": "noop"}
        n = len(posts)
        base, rem = divmod(qty, n)
        for i, p in enumerate(posts):
            dests.append((p, base + (1 if i < rem else 0)))
    else:
        for d in destinations:
            p = str(d.get("postal") or "").strip()
            u = int(d.get("units") or 0)
            if p and u > 0:
                dests.append((p, u))

    total_assigned = sum(u for _, u in dests)
    if total_assigned != qty:
        return None, {
            "status": "skipped",
            "message": f"Destination units sum to {total_assigned}, expected {qty}",
            "recommendation": "noop",
        }

    return dests, None


def scale_consolidated_linehaul_leg(freight: dict[str, Any], multiplier: float) -> dict[str, Any]:
    """
    Apply ``multiplier`` only to the consolidated-path linehaul leg (LTL/FTL mock ``total_usd``).
    Direct multi-origin parcel totals are unchanged. Used to align mock linehaul with contracted
    lane economics and to surface management targets when mocks are conservative.
    """
    m = float(multiplier)
    if m >= 0.9999 and m <= 1.0001:
        return freight
    out = dict(freight)
    at_qty = max(1, int(out.get("at_qty") or 1))
    orig = float(out.get("total_usd") or 0)
    scaled = round(orig * m, 2)
    out["linehaul_total_usd_before_multiplier"] = orig
    out["applied_consolidated_linehaul_multiplier"] = m
    out["total_usd"] = scaled
    if "linehaul_usd_per_unit_at_this_qty" in out:
        out["linehaul_usd_per_unit_at_this_qty"] = round(scaled / at_qty, 6)
    return out

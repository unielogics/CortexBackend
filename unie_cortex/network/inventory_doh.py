"""Days-on-hand and simple storage / velocity signals (inventory intelligence)."""

from __future__ import annotations

from typing import Any


def compute_days_on_hand(
    on_hand_units: float,
    avg_daily_demand_units: float,
) -> dict[str, Any]:
    """DOH = on_hand / daily velocity; guardrails when velocity unknown."""
    oh = max(0.0, float(on_hand_units))
    vel = float(avg_daily_demand_units)

    if vel <= 0:
        return {
            "status": "skipped",
            "days_on_hand": None,
            "message": "avg_daily_demand_units must be positive for DOH",
        }

    doh = oh / vel
    return {
        "status": "complete",
        "on_hand_units": round(oh, 3),
        "avg_daily_demand_units": round(vel, 4),
        "days_on_hand": round(doh, 2),
    }


def inventory_signals(
    *,
    on_hand_units: float,
    avg_daily_demand_units: float,
    target_days_min: float = 7.0,
    target_days_max: float = 45.0,
    reorder_point_days: float = 10.0,
    case_pack_units: float | None = None,
) -> dict[str, Any]:
    """
    Ongoing suggestion scaffold: overstock / understock vs band, reorder quantity hint.
    """
    base = compute_days_on_hand(on_hand_units, avg_daily_demand_units)
    if base["status"] != "complete":
        return {**base, "suggestion": None}

    doh = base["days_on_hand"]
    assert doh is not None
    suggestion: dict[str, Any] = {"severity": "ok", "action": "monitor", "detail": ""}

    if doh < target_days_min:
        suggestion = {
            "severity": "high",
            "action": "replenish_or_transfer",
            "detail": f"DOH {doh} below target min {target_days_min} — risk of stockout.",
        }
    elif doh > target_days_max:
        suggestion = {
            "severity": "medium",
            "action": "slow_replenishment_or_promote",
            "detail": f"DOH {doh} above target max {target_days_max} — storage carrying cost pressure.",
        }

    reorder_units = None
    if avg_daily_demand_units > 0:
        reorder_units = max(0.0, (reorder_point_days * avg_daily_demand_units) - on_hand_units)
        if case_pack_units and case_pack_units > 0:
            packs = int((reorder_units + case_pack_units - 1) // case_pack_units)
            reorder_units = packs * case_pack_units

    return {
        **base,
        "targets": {"days_min": target_days_min, "days_max": target_days_max},
        "reorder_point_days": reorder_point_days,
        "suggested_reorder_units": round(reorder_units, 2) if reorder_units is not None else None,
        "suggestion": suggestion,
        "storage_note": "Tie to cube/pallet positions when SKU dims available in catalog.",
    }

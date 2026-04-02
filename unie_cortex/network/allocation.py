"""Allocate shared linehaul (LTL/FTL pallet) cost across tenants or SKUs."""

from __future__ import annotations

from typing import Any, Literal

AllocationMethod = Literal["by_weight", "by_cube"]


def allocate_linehaul_cost(
    total_usd: float,
    shares: list[dict[str, Any]],
    *,
    method: AllocationMethod = "by_weight",
) -> dict[str, Any]:
    """
    ``shares``: [{ \"tenant_id\": \"a\", \"weight_lb\": 400, \"cube_cuft\": 12 }, ...]

    Returns each row with ``allocated_linehaul_usd`` summing to ``total_usd`` (rounded).
    """
    if not shares:
        return {"status": "skipped", "message": "no shares", "lines": []}

    t = float(total_usd)
    if t <= 0:
        return {
            "status": "complete",
            "method": method,
            "total_usd": 0.0,
            "lines": [{**s, "allocated_linehaul_usd": 0.0} for s in shares],
        }

    if method == "by_weight":
        denom = sum(max(0.0, float(s.get("weight_lb") or 0)) for s in shares)
        if denom <= 0:
            denom = float(len(shares))
            weights = [1.0] * len(shares)
        else:
            weights = [max(0.0, float(s.get("weight_lb") or 0)) for s in shares]
    else:
        denom = sum(max(0.0, float(s.get("cube_cuft") or 0)) for s in shares)
        if denom <= 0:
            denom = float(len(shares))
            weights = [1.0] * len(shares)
        else:
            weights = [max(0.0, float(s.get("cube_cuft") or 0)) for s in shares]

    raw = [t * (w / denom) for w in weights]
    rounded = [round(x, 2) for x in raw]
    drift = round(t - sum(rounded), 2)
    if rounded and abs(drift) >= 0.01:
        rounded[-1] = round(rounded[-1] + drift, 2)

    lines = []
    for s, alloc in zip(shares, rounded, strict=True):
        row = dict(s)
        row["allocated_linehaul_usd"] = alloc
        lines.append(row)

    return {
        "status": "complete",
        "method": method,
        "total_usd": round(t, 2),
        "lines": lines,
    }

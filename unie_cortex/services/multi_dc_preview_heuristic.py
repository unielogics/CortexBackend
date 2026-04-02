"""Heuristic ``MultiDcBody`` builder from order_lines + a primary DC (explicit follow-up to strategy suggestions)."""

from __future__ import annotations

from collections import Counter
from typing import Any


def build_multi_dc_preview_body_heuristic(
    *,
    order_lines: list[dict[str, Any]],
    primary_warehouse: dict[str, Any],
    max_lanes: int = 12,
) -> dict[str, Any]:
    """
    Build ``{warehouses, lanes}`` for POST /v1/assessment/multi-dc-preview.

    ``primary_warehouse`` must include ``id``, ``lat``, ``lon`` (and optional ``label``).
    Lanes aggregate destination ZIP5 from order lines into rough utilization hints — not a substitute
    for real lane demand + coordinates used in production cuOpt flows.
    """
    wh = dict(primary_warehouse)
    wid = wh.get("id") or "primary"
    wh.setdefault("id", wid)

    zips = [
        str(r.get("ship_to_postal") or "").strip()[:5]
        for r in order_lines
        if (r.get("ship_to_postal") or "").strip()
    ]
    zips = [z for z in zips if len(z) >= 3]
    if not zips:
        return {
            "warehouses": [wh],
            "lanes": [],
            "note": "No ship_to_postal on order_lines — add destinations before multi-dc-preview.",
        }

    ctr = Counter(zips)
    top = ctr.most_common(max(1, max_lanes))
    total = sum(c for _, c in top) or 1
    lanes: list[dict[str, Any]] = []
    for dest_zip, n in top:
        share = n / total
        lanes.append(
            {
                "from_id": wid,
                "to_id": f"dest_{dest_zip}",
                "utilization_pct": min(98.0, round(35.0 + 55.0 * share, 1)),
                "monthly_units_estimate": int(n),
            }
        )
    return {"warehouses": [wh], "lanes": lanes}

"""TMS-oriented lane volume rollup (shared routes / broker tender hints)."""

from __future__ import annotations

import re
from typing import Any


def _zip3(postal: str | None) -> str:
    if not postal:
        return "UNK"
    d = re.sub(r"\D", "", str(postal).strip())[:5]
    return d[:3].zfill(3) if len(d) >= 3 else "UNK"


def rollup_lanes_from_labels(
    labels: list[dict[str, Any]],
    *,
    top_n: int = 25,
) -> dict[str, Any]:
    """
    Groups by (origin_zip3, dest_zip3) for volume that could be consolidated on linehaul.
    """
    from collections import defaultdict

    lanes: dict[tuple[str, str], dict[str, float]] = defaultdict(
        lambda: {"shipments": 0, "total_weight_lb": 0.0, "total_label_usd": 0.0}
    )

    for row in labels:
        o = _zip3(row.get("origin_postal"))
        d = _zip3(row.get("dest_postal"))
        if d == "UNK":
            continue
        key = (o, d)
        lanes[key]["shipments"] += 1
        try:
            w = float(row.get("weight_lb") or 0)
            if w > 0:
                lanes[key]["total_weight_lb"] += w
        except (TypeError, ValueError):
            pass
        try:
            la = row.get("label_amount_usd")
            if la is not None:
                lanes[key]["total_label_usd"] += float(la)
        except (TypeError, ValueError):
            pass

    if not lanes:
        return {"status": "skipped", "message": "No lane keys from labels", "lanes": []}

    ranked = sorted(
        lanes.items(),
        key=lambda kv: kv[1]["shipments"],
        reverse=True,
    )[:top_n]

    out_lanes = []
    for (o3, d3), stats in ranked:
        out_lanes.append(
            {
                "origin_zip3": o3,
                "dest_zip3": d3,
                "shipment_count": int(stats["shipments"]),
                "total_weight_lb": round(stats["total_weight_lb"], 2),
                "total_label_usd": round(stats["total_label_usd"], 2),
                "tms_hint": "High repeated lane — candidate for multi-stop FTL/LTL or pooled tender.",
            }
        )

    return {
        "status": "complete",
        "lane_count": len(lanes),
        "top_lanes": out_lanes,
        "notes": "Use for broker RFPs and cross-client consolidation where contractually allowed.",
    }

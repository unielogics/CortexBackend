"""TMS-oriented lane volume rollup (shared routes / broker tender hints)."""

from __future__ import annotations

import re
from typing import Any

# Pre-compile non-digit regex to avoid re-compilation in hot postal parsing loops
_RE_NON_DIGIT = re.compile(r"\D")


def _zip3(postal: str | None) -> str:
    """Extracts 3-digit ZIP prefix from postal codes with fast-path string checks."""
    if not postal:
        return "UNK"
    s = str(postal).strip()
    n = len(s)
    # Fast path for standard 5-digit ZIPs (e.g. "90210")
    if n == 5 and s.isdigit():
        return s[:3]
    # Fast path for standard ZIP+4 formats (e.g. "90210-1234")
    if n == 10 and s[5] == "-" and s[:5].isdigit() and s[6:].isdigit():
        return s[:3]
    # Fast path for unhyphenated 9-digit ZIPs (e.g. "902101234")
    if n == 9 and s.isdigit():
        return s[:3]
    # Fast path for 3 or 4-digit numeric prefixes (e.g. "902" or "0123")
    if (n == 3 or n == 4) and s.isdigit():
        return s[:3].zfill(3)

    # Fallback to regex stripping for non-standard postal formats
    d = _RE_NON_DIGIT.sub("", s)[:5]
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

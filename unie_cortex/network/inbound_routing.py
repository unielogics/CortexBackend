"""Inbound: find closest warehouse to an arbitrary US receipt ZIP (first touch)."""

from __future__ import annotations

import re
from typing import Any


def _zip3(postal: str | None) -> str | None:
    if not postal:
        return None
    d = re.sub(r"\D", "", postal.strip())[:5]
    if len(d) < 3:
        return None
    return d[:3].zfill(3)


def zip3_distance_proxy(a: str, b: str) -> int:
    """Deterministic distance proxy (not miles). Smaller = closer in ZIP3 space."""
    za, zb = _zip3(a), _zip3(b)
    if not za or not zb:
        return 9999
    return abs(int(za) - int(zb))


def closest_node_by_postal(
    receipt_postal: str,
    nodes: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """
    ``nodes``: [{ \"warehouse_id\": \"NJ\", \"postal\": \"07001\" }, ...]
    Returns chosen node + all candidates sorted by proxy distance.
    """
    if not nodes:
        return None
    scored: list[tuple[int, dict[str, Any]]] = []
    for n in nodes:
        p = str(n.get("postal") or "").strip()
        if not p:
            continue
        d = zip3_distance_proxy(receipt_postal, p)
        scored.append((d, n))
    if not scored:
        return None
    scored.sort(key=lambda x: x[0])
    best_d, best = scored[0]
    return {
        "receipt_postal": receipt_postal,
        "closest": {
            "warehouse_id": best.get("warehouse_id"),
            "postal": str(best.get("postal") or "").strip(),
            "zip3_distance_proxy": best_d,
        },
        "candidates_ranked": [
            {
                "warehouse_id": n.get("warehouse_id"),
                "postal": str(n.get("postal") or "").strip(),
                "zip3_distance_proxy": d,
            }
            for d, n in scored
        ],
        "note": "Use for first-touch receiving; follow with linehaul from this node. Proxy is ZIP3 delta, not road miles.",
    }

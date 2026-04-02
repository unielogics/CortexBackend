"""Ballpark ground transit days (planning only — not carrier SLAs)."""

from __future__ import annotations

from typing import Any

from unie_cortex.network.inbound_routing import zip3_distance_proxy


def estimate_ground_transit_days(origin_postal: str, dest_postal: str) -> dict[str, Any]:
    """
    Mock bands from ZIP3 separation — mimics **economy/ground** (not expedited).
    Target typical **2–5** calendar days for CONUS-style lanes in planning mocks.
    """
    d = zip3_distance_proxy(origin_postal, dest_postal)
    if d <= 15:
        lo, hi = 2, 3
    elif d <= 120:
        lo, hi = 3, 4
    else:
        lo, hi = 4, 5
    return {
        "days_min": lo,
        "days_max": hi,
        "zip3_distance_proxy": d,
        "model": "mock_ground_zip3_bands_v1",
        "note": "Planning band only; real transit depends on carrier, service level, and induction time.",
    }

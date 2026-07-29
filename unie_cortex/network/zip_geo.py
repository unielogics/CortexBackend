"""
Map destination ZIP3 to contiguous U.S. state via nearest mock-grid hub metro.
"""

from __future__ import annotations

import functools
import math

from unie_cortex.services.warehouse_mock_rate_grid import (
    CONTIGUOUS_STATE_HUB_DESTINATIONS_48,
    _zip5_to_latlon,
)

# Precompute state hub coordinates in radians, including sine/cosine of latitude
# to avoid redundant calculations in hot loops.
_STATE_HUBS_RAD = [
    (
        str(m["state"]),
        math.sin(math.radians(float(m["lat"]))),
        math.cos(math.radians(float(m["lat"]))),
        math.radians(float(m["lon"])),
    )
    for m in CONTIGUOUS_STATE_HUB_DESTINATIONS_48
]


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Legacy Haversine distance in km (retained for backward compatibility)."""
    r = 6371.0
    la1, lo1, la2, lo2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat, dlon = la2 - la1, lo2 - lo1
    h = math.sin(dlat / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(min(1.0, h)))


@functools.lru_cache(maxsize=1024)
def nearest_contiguous_state_for_zip3(zip3: str) -> str | None:
    """
    Finds the nearest contiguous U.S. state for a 3-digit ZIP prefix.

    Optimized:
    1. Decorated with functools.lru_cache to make repetitive lookups O(1).
    2. Uses the Spherical Law of Cosines to find the nearest hub, which avoids
       expensive trig conversions, square roots, and arcsine functions inside the loop.
    """
    z = (zip3 or "").strip()
    if not z.isdigit():
        z = "".join(c for c in z if c.isdigit())
    if len(z) < 3:
        return None
    z3 = z[:3].zfill(3)
    z5 = z3 + "01"
    ll = _zip5_to_latlon(z5)
    if not ll:
        return None
    la, lo = ll

    # Fast path: Spherical law of cosines dot-product metric to find the nearest hub.
    # Maximizing cos(d) is mathematically identical to minimizing the distance d.
    la_rad = math.radians(la)
    lo_rad = math.radians(lo)
    sin_la = math.sin(la_rad)
    cos_la = math.cos(la_rad)

    best_st: str | None = None
    best_metric = -2.0  # Cosine metric range is [-1.0, 1.0]

    for st, sin_lat2, cos_lat2, lon2 in _STATE_HUBS_RAD:
        metric = sin_la * sin_lat2 + cos_la * cos_lat2 * math.cos(lon2 - lo_rad)
        if metric > best_metric:
            best_metric = metric
            best_st = st

    return best_st

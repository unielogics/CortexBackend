"""
Map destination ZIP3 to contiguous U.S. state via nearest mock-grid hub metro.
"""

from __future__ import annotations

from functools import lru_cache
import math

from unie_cortex.services.warehouse_mock_rate_grid import (
    CONTIGUOUS_STATE_HUB_DESTINATIONS_48,
    _zip5_to_latlon,
)

# Pre-compute static hub coordinates in radians once at the module level
# This avoids doing math.radians, float cast, and dict lookup in hot loops.
_STATE_HUB_RADS = [
    (
        math.radians(float(m["lat"])),
        math.radians(float(m["lon"])),
        str(m["state"])
    )
    for m in CONTIGUOUS_STATE_HUB_DESTINATIONS_48
]


def _haversine_km_optimized(la1: float, lo1: float, la2: float, lo2: float) -> float:
    """Computes distance between two coordinate pairs already converted to radians."""
    r = 6371.0
    dlat, dlon = la2 - la1, lo2 - lo1
    h = math.sin(dlat / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(min(1.0, h)))


@lru_cache(maxsize=1024)
def nearest_contiguous_state_for_zip3(zip3: str) -> str | None:
    """
    Finds the nearest contiguous state for a given ZIP3.
    Uses @lru_cache to cache results and pre-computed hub coordinates in radians.
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
    la_deg, lo_deg = ll
    la1 = math.radians(la_deg)
    lo1 = math.radians(lo_deg)

    best_st: str | None = None
    best_km = float("inf")
    for la2, lo2, state in _STATE_HUB_RADS:
        km = _haversine_km_optimized(la1, lo1, la2, lo2)
        if km < best_km:
            best_km = km
            best_st = state
    return best_st

"""
Map destination ZIP3 to contiguous U.S. state via nearest mock-grid hub metro.
"""

from __future__ import annotations

import math
from functools import lru_cache

from unie_cortex.services.warehouse_mock_rate_grid import (
    CONTIGUOUS_STATE_HUB_DESTINATIONS_48,
    _zip5_to_latlon,
)

# Bolt Optimization: Precompute state hub coordinates in radians at module level
# to avoid redundant float parsing, dictionary lookup, and math.radians calls on hot paths.
_STATE_HUBS_RAD = [
    (str(m["state"]), math.radians(float(m["lat"])), math.radians(float(m["lon"])))
    for m in CONTIGUOUS_STATE_HUB_DESTINATIONS_48
]


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    la1, lo1, la2, lo2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat, dlon = la2 - la1, lo2 - lo1
    h = math.sin(dlat / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(min(1.0, h)))


# Bolt Optimization: Cache the function results for the 1000 possible ZIP3 values.
# This completely bypasses string normalization, dictionary center coordinate lookups,
# and O(N) haversine loop calculations on warm/hot paths.
@lru_cache(maxsize=1024)
def nearest_contiguous_state_for_zip3(zip3: str) -> str | None:
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
    la_rad, lo_rad = math.radians(la), math.radians(lo)

    best_st: str | None = None
    best_km = float("inf")
    r = 6371.0

    # Fast path: compute haversine distance using pre-computed radians coordinates
    for state, la2_rad, lo2_rad in _STATE_HUBS_RAD:
        dlat, dlon = la2_rad - la_rad, lo2_rad - lo_rad
        h = math.sin(dlat / 2) ** 2 + math.cos(la_rad) * math.cos(la2_rad) * math.sin(dlon / 2) ** 2
        km = 2 * r * math.asin(math.sqrt(min(1.0, h)))
        if km < best_km:
            best_km = km
            best_st = state

    return best_st

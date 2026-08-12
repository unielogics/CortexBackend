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


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    la1, lo1, la2, lo2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat, dlon = la2 - la1, lo2 - lo1
    h = math.sin(dlat / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(min(1.0, h)))


# Pre-compute contiguous US state hub coordinates in radians at the module level
# to avoid redundant conversions, dictionary lookups, and float parses.
_STATE_HUBS_RAD = [
    (str(m["state"]), math.radians(float(m["lat"])), math.radians(float(m["lon"])))
    for m in CONTIGUOUS_STATE_HUB_DESTINATIONS_48
]


@functools.lru_cache(maxsize=1024)
def nearest_contiguous_state_for_zip3(zip3: str) -> str | None:
    """
    Map destination ZIP3 to contiguous U.S. state via nearest mock-grid hub metro.
    Optimized with module-level pre-computed radians and caching.
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

    la1, lo1 = math.radians(ll[0]), math.radians(ll[1])
    cos_la1 = math.cos(la1)

    best_st: str | None = None
    best_h = float("inf")

    # Inline and optimize haversine distance comparison by avoiding math.asin,
    # scale factor multiplication, and redundant math.radians conversions.
    for st, la2, lo2 in _STATE_HUBS_RAD:
        dlat = la2 - la1
        dlon = lo2 - lo1
        h = math.sin(dlat / 2) ** 2 + cos_la1 * math.cos(la2) * math.sin(dlon / 2) ** 2
        if h < best_h:
            best_h = h
            best_st = st

    return best_st

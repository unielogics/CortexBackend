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

# PERFORMANCE OPTIMIZATION (Bolt ⚡): Pre-compute hub coordinates in radians
# at the module level to avoid math.radians conversions and dictionary lookups
# in hot loops. This avoids O(N) conversions per lookup call.
_STATE_HUB_RADS = [
    (
        math.radians(float(m["lat"])),
        math.radians(float(m["lon"])),
        math.cos(math.radians(float(m["lat"]))),
        str(m["state"]),
    )
    for m in CONTIGUOUS_STATE_HUB_DESTINATIONS_48
]


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    la1, lo1, la2, lo2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat, dlon = la2 - la1, lo2 - lo1
    h = math.sin(dlat / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(min(1.0, h)))


# PERFORMANCE OPTIMIZATION (Bolt ⚡): Cache lookup results for normalized 3-digit
# ZIP codes. Since there are only 1,000 possible 3-digit ZIP codes (000-999),
# a maxsize of 1024 ensures zero cache eviction once filled, achieving O(1) performance.
@functools.lru_cache(maxsize=1024)
def _nearest_contiguous_state_for_zip3_cached(z3: str) -> str | None:
    z5 = z3 + "01"
    ll = _zip5_to_latlon(z5)
    if not ll:
        return None
    la1 = math.radians(ll[0])
    lo1 = math.radians(ll[1])
    cos_la1 = math.cos(la1)

    r = 6371.0
    best_st: str | None = None
    best_km = float("inf")

    # Fast haversine computation with pre-computed values
    for la2, lo2, cos_la2, state in _STATE_HUB_RADS:
        dlat = la2 - la1
        dlon = lo2 - lo1
        h = (
            math.sin(dlat / 2) ** 2
            + cos_la1 * cos_la2 * math.sin(dlon / 2) ** 2
        )
        km = 2 * r * math.asin(math.sqrt(min(1.0, h)))
        if km < best_km:
            best_km = km
            best_st = state

    return best_st


def nearest_contiguous_state_for_zip3(zip3: str) -> str | None:
    z = (zip3 or "").strip()
    if not z.isdigit():
        z = "".join(c for c in z if c.isdigit())
    if len(z) < 3:
        return None
    z3 = z[:3].zfill(3)
    return _nearest_contiguous_state_for_zip3_cached(z3)

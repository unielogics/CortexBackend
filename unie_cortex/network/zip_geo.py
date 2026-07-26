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

# Precompute static hub coordinates in radians to avoid repeated conversion in hot loops
_STATE_HUBS_RAD: list[tuple[str, float, float, float]] = [
    (
        str(m["state"]),
        math.radians(float(m["lat"])),
        math.radians(float(m["lon"])),
        math.cos(math.radians(float(m["lat"]))),
    )
    for m in CONTIGUOUS_STATE_HUB_DESTINATIONS_48
]


@lru_cache(maxsize=1024)
def nearest_contiguous_state_for_zip3(zip3: str) -> str | None:
    """
    Finds the nearest contiguous U.S. state for a given ZIP3 prefix.
    Utilizes caching (LRU Cache) and pre-calculated module-level radian hub values
    to minimize redundant math operations.
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
    la_rad = math.radians(la)
    lo_rad = math.radians(lo)
    cos_la = math.cos(la_rad)

    best_st: str | None = None
    best_km = float("inf")
    for st, h_la, h_lo, h_cos_la in _STATE_HUBS_RAD:
        # Specialized inlined optimized distance comparison
        dlat = h_la - la_rad
        dlon = h_lo - lo_rad
        h = math.sin(dlat / 2) ** 2 + cos_la * h_cos_la * math.sin(dlon / 2) ** 2
        km = 2 * 6371.0 * math.asin(math.sqrt(min(1.0, h)))
        if km < best_km:
            best_km = km
            best_st = st
    return best_st

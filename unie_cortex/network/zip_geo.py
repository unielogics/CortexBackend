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

# Pre-compute hub coordinates in radians to avoid redundant float/math/dict conversions in hot loop
_STATE_HUBS_RAD: tuple[tuple[str, float, float], ...] = tuple(
    (str(m["state"]), math.radians(float(m["lat"])), math.radians(float(m["lon"])))
    for m in CONTIGUOUS_STATE_HUB_DESTINATIONS_48
)


@functools.lru_cache(maxsize=1024)
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
    la, lo = math.radians(ll[0]), math.radians(ll[1])
    best_st: str | None = None
    best_km = float("inf")
    for state, h_lat, h_lon in _STATE_HUBS_RAD:
        dlat, dlon = h_lat - la, h_lon - lo
        h = math.sin(dlat / 2) ** 2 + math.cos(la) * math.cos(h_lat) * math.sin(dlon / 2) ** 2
        km = 2 * 6371.0 * math.asin(math.sqrt(min(1.0, h)))
        if km < best_km:
            best_km = km
            best_st = state
    return best_st

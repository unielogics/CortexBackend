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

# Precompute the hub coordinates in radians and pre-calculate their trigonometric values
# to avoid expensive conversions and function calls in hot loops.
_STATE_HUBS_RAD = [
    {
        "state": str(m["state"]),
        "sin_lat": math.sin(math.radians(float(m["lat"]))),
        "cos_lat": math.cos(math.radians(float(m["lat"]))),
        "sin_lon": math.sin(math.radians(float(m["lon"]))),
        "cos_lon": math.cos(math.radians(float(m["lon"]))),
    }
    for m in CONTIGUOUS_STATE_HUB_DESTINATIONS_48
]


@functools.lru_cache(maxsize=1024)
def nearest_contiguous_state_for_zip3(zip3: str) -> str | None:
    """
    Returns the closest contiguous state for the given ZIP3.
    Uses an LRU cache and a high-performance distance check via the spherical law of cosines.
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

    # Convert query coordinates to radians
    la1 = math.radians(ll[0])
    lo1 = math.radians(ll[1])

    sin_la1 = math.sin(la1)
    cos_la1 = math.cos(la1)
    sin_lo1 = math.sin(lo1)
    cos_lo1 = math.cos(lo1)

    best_st: str | None = None
    best_cos_d = -2.0  # Cosine of distance ranges from -1 to 1; -2.0 is a safe initial minimum

    for hub in _STATE_HUBS_RAD:
        # Using spherical law of cosines: cos(d) = sin(lat1)sin(lat2) + cos(lat1)cos(lat2)cos(lon1 - lon2)
        # Expanding cos(lon1 - lon2) as cos(lon1)cos(lon2) + sin(lon1)sin(lon2)
        cos_d = sin_la1 * hub["sin_lat"] + cos_la1 * hub["cos_lat"] * (
            cos_lo1 * hub["cos_lon"] + sin_lo1 * hub["sin_lon"]
        )
        if cos_d > best_cos_d:
            best_cos_d = cos_d
            best_st = hub["state"]

    return best_st

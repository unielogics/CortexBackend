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

# Spherical Law of Cosines distance is used for high-performance distance calculation
# Pre-calculate the sines and cosines of the coordinates of the 48 contiguous state hubs
_STATE_HUBS_RAD = [
    (
        math.radians(float(m["lat"])),
        math.radians(float(m["lon"])),
        math.sin(math.radians(float(m["lat"]))),
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
    la, lo = ll

    # Convert target coordinates to radians
    lat_r = math.radians(la)
    lon_r = math.radians(lo)
    sin_lat_r = math.sin(lat_r)
    cos_lat_r = math.cos(lat_r)

    best_st: str | None = None
    # Use Spherical Law of Cosines: cos(d) = sin(lat1)*sin(lat2) + cos(lat1)*cos(lat2)*cos(lon2-lon1)
    # Minimizing distance is equivalent to maximizing cos(d).
    # Since cosine can go from -1 to 1, we start with a value smaller than -1.
    best_cos_d = -2.0

    for lat_hub, lon_hub, sin_lat_hub, cos_lat_hub, state in _STATE_HUBS_RAD:
        cos_d = sin_lat_r * sin_lat_hub + cos_lat_r * cos_lat_hub * math.cos(lon_hub - lon_r)
        if cos_d > best_cos_d:
            best_cos_d = cos_d
            best_st = state
    return best_st

"""
Map destination ZIP3 to contiguous U.S. state via nearest mock-grid hub metro.
"""

from __future__ import annotations

import math

from unie_cortex.services.warehouse_mock_rate_grid import (
    CONTIGUOUS_STATE_HUB_DESTINATIONS_48,
    _zip5_to_latlon,
)


_RAD_CONV = math.pi / 180.0


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    la1 = lat1 * _RAD_CONV
    la2 = lat2 * _RAD_CONV
    dlat = (lat2 - lat1) * _RAD_CONV
    dlon = (lon2 - lon1) * _RAD_CONV
    sin_dlat = math.sin(dlat * 0.5)
    sin_dlon = math.sin(dlon * 0.5)
    h = sin_dlat * sin_dlat + math.cos(la1) * math.cos(la2) * sin_dlon * sin_dlon
    return 12742.0 * math.asin(math.sqrt(min(1.0, h)))


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
    best_st: str | None = None
    best_km = float("inf")
    for m in CONTIGUOUS_STATE_HUB_DESTINATIONS_48:
        km = _haversine_km(la, lo, float(m["lat"]), float(m["lon"]))
        if km < best_km:
            best_km = km
            best_st = str(m["state"])
    return best_st

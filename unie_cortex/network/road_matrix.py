"""Road-network OD distances via OSRM table API with TTL cache and haversine fallback."""

from __future__ import annotations

import math
import threading
import time
from typing import Literal

import httpx

from unie_cortex.config import settings

DistanceSource = Literal["road_network", "great_circle_fallback"]

_OSRM_DEMO = "https://router.project-osrm.org"


def _round_ll(lat: float, lon: float, nd: int = 4) -> tuple[float, float]:
    return round(lat, nd), round(lon, nd)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    la1, lo1, la2, lo2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat, dlon = la2 - la1, lo2 - lo1
    h = math.sin(dlat / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(min(1.0, h)))


def _chain_cache_key(base: str, coords: list[tuple[float, float]]) -> str:
    parts = [_round_ll(lat, lon) for lat, lon in coords]
    return f"{base}|{parts}"


class RoadMatrixProvider:
    """Fetches driving distances; falls back to great-circle when disabled or on error."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._chain_cache: dict[str, tuple[float, tuple[list[float], list[DistanceSource]]]] = {}

    def _base_url(self) -> str | None:
        p = (settings.road_matrix_provider or "none").strip().lower()
        if p in ("", "none", "off", "false"):
            return None
        if p == "osrm_demo":
            return _OSRM_DEMO
        if p == "osrm":
            u = (settings.road_matrix_osrm_base_url or "").strip().rstrip("/")
            return u or None
        return None

    def _ttl(self) -> float:
        return max(60.0, float(settings.road_matrix_cache_ttl_seconds or 3600))

    def _timeout(self) -> float:
        return max(1.0, float(settings.road_matrix_request_timeout_seconds or 8.0))

    def _get_chain_cached(self, key: str) -> tuple[list[float], list[DistanceSource]] | None:
        with self._lock:
            hit = self._chain_cache.get(key)
            if not hit:
                return None
            exp, payload = hit
            if time.monotonic() > exp:
                del self._chain_cache[key]
                return None
            return payload

    def _set_chain_cached(
        self, key: str, legs_km: list[float], srcs: list[DistanceSource]
    ) -> None:
        with self._lock:
            self._chain_cache[key] = (time.monotonic() + self._ttl(), (legs_km, srcs))

    def _osrm_table_m_km(
        self, base: str, coords: list[tuple[float, float]]
    ) -> tuple[list[float] | None, list[DistanceSource] | None]:
        """Return adjacent-leg distances in km, or None if table failed entirely."""
        if len(coords) < 2:
            return [], []
        coord_str = ";".join(f"{lon},{lat}" for lat, lon in coords)
        url = f"{base}/table/v1/driving/{coord_str}"
        params = {"annotations": "distance,duration"}
        with httpx.Client(timeout=self._timeout()) as client:
            r = client.get(url, params=params)
            r.raise_for_status()
            data = r.json()
        if data.get("code") != "Ok":
            return None, None
        dists = data.get("distances")
        if not dists or not isinstance(dists, list):
            return None, None
        out: list[float] = []
        srcs: list[DistanceSource] = []
        for i in range(len(coords) - 1):
            row = dists[i] if i < len(dists) else None
            if row is None or i + 1 >= len(row):
                return None, None
            m = row[i + 1]
            if m is None:
                la, lo = coords[i]
                la2, lo2 = coords[i + 1]
                out.append(haversine_km(la, lo, la2, lo2))
                srcs.append("great_circle_fallback")
            else:
                out.append(float(m) / 1000.0)
                srcs.append("road_network")
        return out, srcs

    def distances_along_chain(
        self, coords: list[tuple[float, float]]
    ) -> tuple[list[float], list[DistanceSource]]:
        """Driving distance in km for each adjacent pair along ``coords``."""
        if len(coords) < 2:
            return [], []
        base = self._base_url()
        if not base:
            legs = [
                haversine_km(coords[i][0], coords[i][1], coords[i + 1][0], coords[i + 1][1])
                for i in range(len(coords) - 1)
            ]
            return legs, ["great_circle_fallback"] * len(legs)

        ck = _chain_cache_key(base, coords)
        cached = self._get_chain_cached(ck)
        if cached:
            return cached

        try:
            legs, srcs = self._osrm_table_m_km(base, coords)
            if legs is None:
                raise ValueError("osrm_table_failed")
        except Exception:
            legs = [
                haversine_km(coords[i][0], coords[i][1], coords[i + 1][0], coords[i + 1][1])
                for i in range(len(coords) - 1)
            ]
            srcs = ["great_circle_fallback"] * len(legs)

        self._set_chain_cached(ck, legs, srcs)
        return legs, srcs

    def pair_distance_km(self, a: tuple[float, float], b: tuple[float, float]) -> tuple[float, DistanceSource]:
        legs, srcs = self.distances_along_chain([a, b])
        if not legs:
            return 0.0, "great_circle_fallback"
        src: DistanceSource = srcs[0] if srcs else "great_circle_fallback"
        return legs[0], src


_default_provider: RoadMatrixProvider | None = None
_provider_lock = threading.Lock()


def get_road_matrix_provider() -> RoadMatrixProvider:
    global _default_provider
    with _provider_lock:
        if _default_provider is None:
            _default_provider = RoadMatrixProvider()
        return _default_provider


def reset_road_matrix_provider_for_tests() -> None:
    global _default_provider
    with _provider_lock:
        _default_provider = RoadMatrixProvider()

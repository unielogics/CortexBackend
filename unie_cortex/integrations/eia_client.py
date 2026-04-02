"""EIA Open Data API — latest observation for a petroleum price series (sync + TTL cache)."""

from __future__ import annotations

import threading
import time
from typing import Any

import httpx

from unie_cortex.config import settings
from unie_cortex.integrations.eia_series_registry import DEFAULT_REGION_LABEL

_EIA_V1 = "https://api.eia.gov/series"

_lock = threading.Lock()
_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _cache_get(series_id: str) -> dict[str, Any] | None:
    with _lock:
        hit = _cache.get(series_id)
        if not hit:
            return None
        exp, payload = hit
        if time.monotonic() > exp:
            del _cache[series_id]
            return None
        return payload


def _cache_set(series_id: str, payload: dict[str, Any]) -> None:
    ttl = max(300.0, float(settings.eia_cache_ttl_seconds or 86400))
    with _lock:
        _cache[series_id] = (time.monotonic() + ttl, payload)


def clear_eia_cache_for_tests() -> None:
    with _lock:
        _cache.clear()


def fetch_series_latest(series_id: str) -> dict[str, Any]:
    """
    Return normalized snapshot dict or error-shaped dict.

    Success keys: ``ok``, ``price_usd_per_gallon``, ``period``, ``series_id``,
    ``region``, ``source``, ``units``, ``fetched_at_note``.
    """
    if not settings.eia_enabled:
        return {"ok": False, "skipped": True, "reason": "eia_disabled"}
    key = (settings.eia_api_key or "").strip()
    if not key:
        return {"ok": False, "skipped": True, "reason": "eia_api_key_unset"}

    cached = _cache_get(series_id)
    if cached is not None:
        return {**cached, "cached": True}

    params = {"api_key": key, "series_id": series_id}
    timeout = max(2.0, float(settings.eia_request_timeout_seconds or 15.0))
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.get(_EIA_V1, params=params)
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        return {"ok": False, "error": str(e), "series_id": series_id}

    series_list = data.get("series") or []
    if not series_list:
        return {"ok": False, "error": "no_series_in_response", "series_id": series_id}
    s0 = series_list[0]
    rows = s0.get("data") or []
    name = s0.get("name") or ""
    units = s0.get("units") or ""
    price: float | None = None
    period: str | None = None
    for pair in rows:
        if not pair or len(pair) < 2:
            continue
        p, v = pair[0], pair[1]
        if v is None:
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        price = fv
        period = str(p)
        break
    if price is None:
        return {"ok": False, "error": "no_valid_observation", "series_id": series_id}

    out = {
        "ok": True,
        "price_usd_per_gallon": round(price, 4),
        "period": period,
        "series_id": series_id,
        "region": DEFAULT_REGION_LABEL,
        "source": "eia",
        "units": units,
        "series_name": name,
        "note": "Macro EIA benchmark — not a specific truck-stop rack or pump price.",
    }
    _cache_set(series_id, {k: v for k, v in out.items() if k != "cached"})
    return out

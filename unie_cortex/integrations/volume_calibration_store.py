"""
Persistent category-level scale corrections for Keepa-derived monthly volume.

Updates use exponential moving average on observed actual / predicted ratios.
Optional JSON file path from settings.volume_calibration_store_path.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from threading import Lock
from typing import Any


_STATE_LOCK = Lock()
_CACHE: dict[str, Any] | None = None
_CACHE_PATH: str | None = None
_CACHE_MTIME: float | None = None


def _default_state() -> dict[str, Any]:
    return {"version": 1, "categories": {}}


def _load_raw(path: str) -> dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError):
        return _default_state()
    if not isinstance(raw, dict):
        return _default_state()
    cats = raw.get("categories")
    if not isinstance(cats, dict):
        raw["categories"] = {}
    raw.setdefault("version", 1)
    return raw


def load_calibration_state(path: str | None) -> dict[str, Any]:
    """Return merged calibration state (copy safe for readers)."""
    global _CACHE, _CACHE_PATH, _CACHE_MTIME
    if not path or not str(path).strip():
        return _default_state()
    path = os.path.abspath(str(path).strip())
    try:
        mtime = os.path.getmtime(path) if os.path.isfile(path) else None
    except OSError:
        mtime = None
    with _STATE_LOCK:
        if _CACHE is not None and _CACHE_PATH == path and mtime is not None and _CACHE_MTIME == mtime:
            return json.loads(json.dumps(_CACHE))
        if _CACHE is not None and _CACHE_PATH == path and mtime is None and _CACHE_MTIME is None:
            return json.loads(json.dumps(_CACHE))
        st = _load_raw(path) if mtime is not None else _default_state()
        _CACHE = st
        _CACHE_PATH = path
        _CACHE_MTIME = mtime
        return json.loads(json.dumps(st))


def invalidate_calibration_cache() -> None:
    global _CACHE, _CACHE_PATH, _CACHE_MTIME
    with _STATE_LOCK:
        _CACHE = None
        _CACHE_PATH = None
        _CACHE_MTIME = None


def category_scale_from_state(state: dict[str, Any], category_key: str) -> tuple[float, int]:
    cats = state.get("categories") if isinstance(state.get("categories"), dict) else {}
    row = cats.get(category_key)
    if not isinstance(row, dict):
        return 1.0, 0
    try:
        ema = float(row.get("scale_ema", 1.0))
    except (TypeError, ValueError):
        ema = 1.0
    try:
        n = int(row.get("n_samples", 0) or 0)
    except (TypeError, ValueError):
        n = 0
    ema = max(0.25, min(4.0, ema))
    return ema, n


def save_calibration_state(path: str, state: dict[str, Any]) -> None:
    """Atomically write calibration JSON."""
    path = os.path.abspath(str(path).strip())
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    payload = json.dumps(state, indent=2, sort_keys=True)
    tmp_dir = parent or "."
    fd, tmp = tempfile.mkstemp(prefix="volcal_", suffix=".json", dir=tmp_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
    invalidate_calibration_cache()


@dataclass
class VolumeObservation:
    category_key: str
    predicted_monthly_mid: float
    actual_monthly_units: float


def record_volume_observation(
    path: str | None,
    *,
    category_key: str,
    predicted_monthly_mid: float,
    actual_monthly_units: float,
    alpha: float = 0.15,
) -> dict[str, Any]:
    """
    Online update: scale_ema ← (1-α)*scale_ema + α * clip(actual/predicted).

    When path is None, returns a no-op summary (no persistence).
    """
    if not path or not str(path).strip():
        return {"status": "skipped", "note": "volume_calibration_store_path not set"}
    ck = (category_key or "global").strip() or "global"
    pred = float(predicted_monthly_mid)
    act = float(actual_monthly_units)
    if pred <= 0 or act < 0:
        return {"status": "rejected", "note": "predicted_monthly_mid must be > 0 and actual non-negative"}
    ratio = act / pred
    ratio = max(0.25, min(4.0, ratio))
    a = max(0.01, min(0.5, float(alpha)))

    state = load_calibration_state(path)
    cats: dict[str, Any] = state.setdefault("categories", {})
    prev = cats.get(ck)
    if not isinstance(prev, dict):
        prev = {"scale_ema": 1.0, "n_samples": 0}
    old_ema = float(prev.get("scale_ema", 1.0))
    old_ema = max(0.25, min(4.0, old_ema))
    new_ema = (1.0 - a) * old_ema + a * ratio
    new_ema = max(0.25, min(4.0, new_ema))
    n = int(prev.get("n_samples", 0) or 0) + 1
    cats[ck] = {"scale_ema": round(new_ema, 6), "n_samples": n, "last_ratio": round(ratio, 6)}
    save_calibration_state(path, state)
    return {
        "status": "recorded",
        "category_key": ck,
        "scale_ema_before": round(old_ema, 6),
        "scale_ema_after": round(new_ema, 6),
        "ratio_applied": round(ratio, 6),
        "n_samples": n,
    }

"""Load Prep Center warehouse bundle shipped with Unie Cortex (generated JSON)."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

_BUNDLE_NAME = "prep_center_candidate_warehouses.json"


def _bundle_path() -> Path:
    return Path(__file__).resolve().parent / "data" / _BUNDLE_NAME


@lru_cache(maxsize=1)
def load_prep_center_bundle() -> dict[str, Any] | None:
    """
    Return parsed bundle dict with ``baseline_warehouse_id`` and ``candidate_warehouses``,
    or None if the fixture file is absent.
    """
    path = _bundle_path()
    if not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    whs = data.get("candidate_warehouses")
    if not isinstance(whs, list) or not whs:
        return None
    return data


def prep_center_candidate_warehouses_raw() -> list[dict[str, Any]] | None:
    b = load_prep_center_bundle()
    if not b:
        return None
    out = b.get("candidate_warehouses")
    return out if isinstance(out, list) else None


def prep_center_baseline_warehouse_id() -> str | None:
    override = (os.environ.get("PREP_CENTER_BASELINE_WAREHOUSE_ID") or "").strip()
    if override:
        return override
    b = load_prep_center_bundle()
    if not b:
        return None
    bid = b.get("baseline_warehouse_id")
    return str(bid).strip() if bid else None


def prep_center_baseline_row() -> dict[str, Any] | None:
    """Single primary warehouse row for audit baseline (matches one candidate)."""
    whs = prep_center_candidate_warehouses_raw()
    if not whs:
        return None
    bid = prep_center_baseline_warehouse_id()
    if bid:
        for w in whs:
            if isinstance(w, dict) and str(w.get("id") or "").strip() == bid:
                return w
    first = whs[0]
    return first if isinstance(first, dict) else None

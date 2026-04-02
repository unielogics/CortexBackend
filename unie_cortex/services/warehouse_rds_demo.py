"""Bundled Prep Center–style warehouse RDS demo (flat rows + owners + users)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "warehouse_rds_demo.json"


@lru_cache(maxsize=1)
def _load_raw() -> dict[str, Any]:
    if not _DATA_FILE.is_file():
        return {
            "meta": {"error": f"Missing data file: {_DATA_FILE}"},
            "warehouses": [],
            "owners": [],
            "warehouse_owner_users": [],
        }
    with _DATA_FILE.open(encoding="utf-8") as f:
        raw: Any = json.load(f)
    if isinstance(raw, list):
        return {
            "meta": {"schema_note": "Top-level JSON array treated as warehouses_flat rows."},
            "warehouses": raw,
            "owners": [],
            "warehouse_owner_users": [],
        }
    if isinstance(raw, dict):
        return raw
    return {
        "meta": {"error": "warehouse_rds_demo.json must be an object or an array of warehouse rows"},
        "warehouses": [],
        "owners": [],
        "warehouse_owner_users": [],
    }


def get_warehouse_rds_demo_bundle() -> dict[str, Any]:
    """
    Return demo payload shaped like PrepCenterNearMe warehouse_rds exports.

    Operators can replace ``unie_cortex/data/warehouse_rds_demo.json`` with merged
    content from warehouses_flat.json / wOwners / warehouse_owner_users.
    """
    raw = _load_raw()
    wh = raw.get("warehouses")
    if isinstance(wh, list):
        warehouses = wh
    else:
        warehouses = []
    owners = raw.get("owners") if isinstance(raw.get("owners"), list) else []
    users = raw.get("warehouse_owner_users") if isinstance(raw.get("warehouse_owner_users"), list) else []
    meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    return {
        "status": "complete",
        "schema_version": "warehouse_rds_demo_bundle_v1",
        "meta": meta,
        "warehouses": warehouses,
        "owners": owners,
        "warehouse_owner_users": users,
    }


def reload_warehouse_rds_demo_cache() -> None:
    """Test hook: clear lru_cache after replacing JSON on disk."""
    _load_raw.cache_clear()

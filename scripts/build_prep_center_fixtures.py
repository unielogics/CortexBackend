#!/usr/bin/env python3
"""
Build Unie Cortex warehouse fixtures from Prep Center RDS export files.

Set PREP_CENTER_EXPORT_DIR to the directory containing:
  - warehouses_flat.json
  - wOwners.ndjson
  - warehouse_owner_users.json

Or pass --export-dir. Writes:
  - unie_cortex/network/data/prep_center_candidate_warehouses.json
  - unie_cortex/network/data/prep_center_owners_snapshot.json (optional NDJSON owners + users)

Example:
  set PREP_CENTER_EXPORT_DIR=C:\\path\\to\\warehouse_rds
  python scripts/build_prep_center_fixtures.py
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _zip5(postal: str | None) -> str | None:
    if not postal:
        return None
    digits = re.sub(r"\D", "", str(postal).strip())[:5]
    return digits.zfill(5) if len(digits) >= 3 else None


def _parse_float_geo(s: Any) -> float | None:
    if s is None:
        return None
    t = str(s).strip()
    if not t:
        return None
    try:
        return float(t)
    except ValueError:
        return None


def _pricing_profile_for_state(state: str | None) -> str:
    st = (state or "").strip().upper()
    if st == "TX":
        return "profile_tx_v1"
    if st == "FL":
        return "profile_fl_v1"
    if st in {"CA", "OR", "WA"}:
        return "profile_ca_v1"
    if st in frozenset(
        {"NJ", "NY", "PA", "DE", "MD", "DC", "CT", "RI", "MA", "VT", "NH", "ME"}
    ):
        return "profile_nj_v1"
    return "profile_nj_v1"


def _row_to_candidate(
    row: dict[str, Any],
    *,
    mongo_id: str,
) -> dict[str, Any]:
    fw = row.get("full_warehouse_json")
    if not isinstance(fw, dict):
        fw = {}
    addr = fw.get("businessAddress")
    if not isinstance(addr, dict):
        addr = {}

    state = (addr.get("state") or row.get("addressState") or "").strip().upper() or None
    postal = _zip5(addr.get("zipCode") or row.get("addressZip"))
    city = (addr.get("city") or row.get("addressCity") or "").strip()
    line1 = (addr.get("address") or "").strip()
    biz = (row.get("businessName") or fw.get("businessName") or row.get("name") or "").strip()
    wh_pub = (row.get("warehouseId") or fw.get("warehouseId") or "").strip()

    label_parts = [p for p in (biz, line1, city, state, postal) if p]
    label = ", ".join(label_parts) if label_parts else wh_pub or mongo_id

    lat = _parse_float_geo(addr.get("lat"))
    lon = _parse_float_geo(addr.get("long"))

    if not postal:
        raise ValueError(f"warehouse {mongo_id}: missing postal / zip")

    out: dict[str, Any] = {
        "id": f"wh_{mongo_id}",
        "postal": postal,
        "label": label,
        "state": state,
        "pricing_profile_id": _pricing_profile_for_state(state),
        "prep_center": {
            "mongo_warehouse_subdoc_id": mongo_id,
            "warehouse_id": wh_pub or None,
            "unielogics_id": row.get("unielogicsId"),
            "owner_email": row.get("ownerEmail"),
            "mongo_owner_id": row.get("mongoOwnerId"),
        },
    }
    if lat is not None:
        out["lat"] = lat
    if lon is not None:
        out["lon"] = lon
    return out


def _load_warehouses_flat(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("rows")
    if not isinstance(rows, list):
        raise ValueError("warehouses_flat.json: missing rows array")
    out: list[dict[str, Any]] = []
    for r in rows:
        if isinstance(r, dict):
            out.append(r)
    return out


def _load_ndjson_owners(path: Path) -> list[dict[str, Any]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    docs: list[dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        docs.append(json.loads(line))
    return docs


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Prep Center → Unie Cortex warehouse JSON.")
    parser.add_argument(
        "--export-dir",
        type=Path,
        default=None,
        help="Directory with warehouses_flat.json, wOwners.ndjson, warehouse_owner_users.json",
    )
    parser.add_argument(
        "--baseline-id",
        type=str,
        default=None,
        help="Candidate id (wh_<mongoSubdocId>) to mark as audit baseline; default first row",
    )
    parser.add_argument(
        "--skip-owners-snapshot",
        action="store_true",
        help="Do not write prep_center_owners_snapshot.json",
    )
    args = parser.parse_args()

    export_dir = args.export_dir
    if export_dir is None:
        env_dir = (os.environ.get("PREP_CENTER_EXPORT_DIR") or "").strip()
        export_dir = Path(env_dir) if env_dir else None
    if not export_dir or not export_dir.is_dir():
        print(
            "ERROR: set PREP_CENTER_EXPORT_DIR or pass --export-dir to a valid directory",
            file=sys.stderr,
        )
        return 1

    wf = export_dir / "warehouses_flat.json"
    if not wf.is_file():
        print(f"ERROR: missing {wf}", file=sys.stderr)
        return 1

    rows = _load_warehouses_flat(wf)
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        mongo_id = str(
            row.get("mongoWarehouseSubdocId")
            or (row.get("full_warehouse_json") or {}).get("_id")
            or ""
        ).strip()
        if not mongo_id:
            continue
        if mongo_id in seen:
            continue
        try:
            cand = _row_to_candidate(row, mongo_id=mongo_id)
        except ValueError as e:
            print(f"SKIP: {e}", file=sys.stderr)
            continue
        seen.add(mongo_id)
        candidates.append(cand)

    baseline_id = (args.baseline_id or "").strip()
    if not baseline_id and candidates:
        baseline_id = candidates[0]["id"]
    if baseline_id and not any(c["id"] == baseline_id for c in candidates):
        print(f"ERROR: --baseline-id {baseline_id!r} not in generated candidates", file=sys.stderr)
        return 1

    bundle = {
        "schema_version": 1,
        "source": "prep_center_warehouse_rds_export",
        "baseline_warehouse_id": baseline_id,
        "candidate_warehouses": candidates,
    }

    data_dir = _repo_root() / "unie_cortex" / "network" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    out_main = data_dir / "prep_center_candidate_warehouses.json"
    out_main.write_text(json.dumps(bundle, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {out_main} ({len(candidates)} warehouses)")

    if not args.skip_owners_snapshot:
        snap: dict[str, Any] = {"schema_version": 1, "owners_ndjson": [], "warehouse_owner_users": None}
        wo = export_dir / "wOwners.ndjson"
        if wo.is_file():
            snap["owners_ndjson"] = _load_ndjson_owners(wo)
        wu = export_dir / "warehouse_owner_users.json"
        if wu.is_file():
            snap["warehouse_owner_users"] = json.loads(wu.read_text(encoding="utf-8"))
        out_snap = data_dir / "prep_center_owners_snapshot.json"
        out_snap.write_text(json.dumps(snap, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {out_snap}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

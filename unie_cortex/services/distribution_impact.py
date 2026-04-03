"""
Monthly unit impact by warehouse and inter-node freight legs from PRO allocation output.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any


SCHEMA_VERSION = "distribution_impact_v1"

_SAFE_JOB_ID = re.compile(r"[^a-zA-Z0-9._-]+")


def _warehouse_display_name(w: dict[str, Any]) -> str:
    wid = str(w.get("id") or "").strip()
    for key in ("display_name", "name"):
        v = w.get(key)
        if v is not None and str(v).strip():
            return str(v).strip()
    return wid


def build_distribution_impact_rows(
    *,
    job_id: str,
    allocation: dict[str, Any] | None,
    warehouses: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Rows for persistence and API: party_type warehouse | freight, party_name, party_id, estimate_monthly_units.
    """
    alloc = allocation if isinstance(allocation, dict) else {}
    if alloc.get("status") == "skipped":
        return []

    id_to_name = {}
    for w in warehouses:
        if not isinstance(w, dict):
            continue
        wid = str(w.get("id") or "").strip()
        if wid:
            id_to_name[wid] = _warehouse_display_name(w)

    wh_units: dict[str, float] = {}
    leg_units: dict[tuple[str, str], float] = {}

    for line in alloc.get("lines") or []:
        if not isinstance(line, dict):
            continue
        for p in line.get("placement") or []:
            if not isinstance(p, dict):
                continue
            wid = str(p.get("warehouse_id") or "").strip()
            if not wid:
                continue
            u = float(p.get("recommended_monthly_units") or 0)
            wh_units[wid] = wh_units.get(wid, 0.0) + u
        for leg in line.get("transfer_from_hub") or []:
            if not isinstance(leg, dict):
                continue
            fid = str(leg.get("from_warehouse_id") or "").strip()
            tid = str(leg.get("to_warehouse_id") or "").strip()
            if not fid or not tid:
                continue
            flow = leg.get("monthly_flow_units")
            if flow is None:
                flow = leg.get("units")
            try:
                u = float(flow or 0)
            except (TypeError, ValueError):
                u = 0.0
            if u <= 0:
                continue
            key = (fid, tid)
            leg_units[key] = leg_units.get(key, 0.0) + u

    rows: list[dict[str, Any]] = []
    for wid in sorted(wh_units.keys()):
        u = wh_units[wid]
        if u <= 0:
            continue
        name = id_to_name.get(wid, wid)
        rows.append(
            {
                "job_id": job_id,
                "party_type": "warehouse",
                "party_id": wid,
                "party_name": name,
                "estimate_monthly_units": round(u, 4) if u != int(u) else int(u),
            }
        )

    for (fid, tid) in sorted(leg_units.keys()):
        u = leg_units[(fid, tid)]
        if u <= 0:
            continue
        fn = id_to_name.get(fid, fid)
        tn = id_to_name.get(tid, tid)
        rows.append(
            {
                "job_id": job_id,
                "party_type": "freight",
                "party_id": f"{fid}→{tid}",
                "party_name": f"{fn}→{tn}",
                "estimate_monthly_units": round(u, 4) if u != int(u) else int(u),
            }
        )

    return rows


def build_distribution_envelope(
    *,
    job_id: str,
    tenant_id: str,
    operational_warehouse_id: str,
    engagement_id: str | None,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "job_id": job_id,
        "tenant_id": tenant_id,
        "operational_warehouse_id": operational_warehouse_id,
        "engagement_id": engagement_id,
        "rows": rows,
    }


def write_distribution_local_file(
    export_dir: str,
    envelope: dict[str, Any],
    *,
    saved_at_iso: str | None = None,
) -> str | None:
    """
    Write one JSON file per job under export_dir. Returns file path or None on skip/failure.
    """
    if not export_dir or not str(export_dir).strip():
        return None
    job_id = str(envelope.get("job_id") or "").strip()
    if not job_id:
        return None
    safe = _SAFE_JOB_ID.sub("_", job_id)[:200] or "job"
    base = os.path.abspath(os.path.expanduser(str(export_dir).strip()))
    try:
        os.makedirs(base, exist_ok=True)
    except OSError:
        return None
    path = os.path.join(base, f"distribution_{safe}.json")
    out = {
        **envelope,
        "saved_at": saved_at_iso or datetime.now(timezone.utc).isoformat(),
    }
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2, default=str)
    except OSError:
        return None
    return path

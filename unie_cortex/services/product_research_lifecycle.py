"""Lifecycle audit/archival utilities for Product Research run artifacts."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from unie_cortex.config import settings
from unie_cortex.db.store import CortexStore
from unie_cortex.integrations.s3_artifacts import (
    head_uri_async,
    put_bytes_async,
    transition_uri_storage_class_async,
)


def _as_iso(v: Any) -> str | None:
    if v is None:
        return None
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return str(v)


def _archive_base(tenant_id: str, warehouse_id: str, run_id: str) -> str:
    prefix = (settings.s3_artifacts_prefix or "").strip().strip("/")
    key = f"archive/product-research/{tenant_id}/{warehouse_id}/{run_id}"
    return f"{prefix}/{key}" if prefix else key


async def _ensure_pointer(
    *,
    run: dict[str, Any],
    field_uri: str,
    field_json: str,
    leaf_name: str,
    dry_run: bool,
) -> tuple[str | None, dict[str, Any]]:
    current_uri = run.get(field_uri)
    if isinstance(current_uri, str) and current_uri.strip():
        head = await head_uri_async(current_uri)
        if head is not None:
            return current_uri, {
                "state": "ok",
                "uri": current_uri,
                "storage_class": head.get("StorageClass") or "STANDARD",
            }
    payload_raw = run.get(field_json)
    if not isinstance(payload_raw, str) or not payload_raw.strip():
        return None, {"state": "missing_payload", "uri": current_uri}
    if dry_run:
        return None, {"state": "would_upload", "uri": current_uri}
    key = f"{_archive_base(str(run.get('tenant_id') or ''), str(run.get('warehouse_id') or ''), str(run.get('id') or ''))}/{leaf_name}"
    new_uri = await put_bytes_async(
        key=key,
        body=payload_raw.encode("utf-8"),
        content_type="application/json",
    )
    return new_uri, {"state": "uploaded", "uri": new_uri}


async def run_product_research_lifecycle_audit(
    *,
    store: CortexStore,
    tenant_id: str | None = None,
    dry_run: bool = True,
    limit: int | None = None,
) -> dict[str, Any]:
    months = int(getattr(settings, "product_research_hot_retention_months", 6) or 6)
    cutoff = datetime.now(timezone.utc) - timedelta(days=30 * max(1, months))
    lim = int(limit or getattr(settings, "product_research_lifecycle_batch_size", 200) or 200)
    runs = await store.product_research_runs_list_for_lifecycle(
        older_than=cutoff,
        tenant_id=(tenant_id or "").strip() or None,
        limit=max(1, lim),
    )
    desired_sc = str(getattr(settings, "product_research_archive_storage_class", "STANDARD_IA") or "STANDARD_IA")
    out_rows: list[dict[str, Any]] = []
    updated = 0
    broken = 0
    for run in runs:
        rid = str(run.get("id") or "")
        if not rid:
            continue
        artifact_uri, artifact_state = await _ensure_pointer(
            run=run,
            field_uri="artifact_s3_uri",
            field_json="artifact_json",
            leaf_name="artifact.json",
            dry_run=dry_run,
        )
        dist_uri, dist_state = await _ensure_pointer(
            run=run,
            field_uri="distribution_s3_uri",
            field_json="distribution_json",
            leaf_name="distribution.json",
            dry_run=dry_run,
        )
        cuopt_req_uri, cuopt_req_state = await _ensure_pointer(
            run=run,
            field_uri="cuopt_request_s3_uri",
            field_json="cuopt_request_json",
            leaf_name="cuopt_request.json",
            dry_run=dry_run,
        )
        cuopt_resp_uri, cuopt_resp_state = await _ensure_pointer(
            run=run,
            field_uri="cuopt_response_s3_uri",
            field_json="cuopt_response_json",
            leaf_name="cuopt_response.json",
            dry_run=dry_run,
        )

        pointer_states = [artifact_state, dist_state, cuopt_req_state, cuopt_resp_state]
        has_broken = any(p.get("state") == "missing_payload" for p in pointer_states)
        if has_broken:
            broken += 1

        lifecycle = {
            "schema_version": "product_research_lifecycle_audit_v1",
            "cutoff_utc": cutoff.isoformat(),
            "audited_at_utc": datetime.now(timezone.utc).isoformat(),
            "hot_retention_months": months,
            "archive_storage_class": desired_sc,
            "pointer_integrity": {
                "artifact": artifact_state,
                "distribution": dist_state,
                "cuopt_request": cuopt_req_state,
                "cuopt_response": cuopt_resp_state,
            },
            "broken": has_broken,
        }

        transitioned: list[str] = []
        if not dry_run:
            for uri in (artifact_uri, dist_uri, cuopt_req_uri, cuopt_resp_uri):
                if not isinstance(uri, str) or not uri.strip():
                    continue
                head = await head_uri_async(uri)
                if head is None:
                    continue
                curr = str(head.get("StorageClass") or "STANDARD").upper()
                target = desired_sc.upper()
                if curr != target:
                    try:
                        ok = await transition_uri_storage_class_async(uri, target)
                        if ok:
                            transitioned.append(uri)
                    except Exception:
                        pass

            merged = dict(run)
            if artifact_uri:
                merged["artifact_s3_uri"] = artifact_uri
            if dist_uri:
                merged["distribution_s3_uri"] = dist_uri
            if cuopt_req_uri:
                merged["cuopt_request_s3_uri"] = cuopt_req_uri
            if cuopt_resp_uri:
                merged["cuopt_response_s3_uri"] = cuopt_resp_uri
            merged["status_reason_code"] = (
                "lifecycle_pointer_broken" if has_broken else str(merged.get("status_reason_code") or "")
            )
            prev_detail = str(merged.get("status_reason_detail") or "").strip()
            note = f" lifecycle_audit={json.dumps(lifecycle, default=str)}"
            merged["status_reason_detail"] = f"{prev_detail}{note}".strip()
            await store.product_research_run_upsert(merged)
            updated += 1

        out_rows.append(
            {
                "run_id": rid,
                "tenant_id": run.get("tenant_id"),
                "warehouse_id": run.get("warehouse_id"),
                "created_at": _as_iso(run.get("created_at")),
                "broken": has_broken,
                "transitioned_count": len(transitioned),
                "pointer_integrity": lifecycle["pointer_integrity"],
            }
        )

    return {
        "schema_version": "product_research_lifecycle_audit_result_v1",
        "dry_run": bool(dry_run),
        "tenant_id": (tenant_id or "").strip() or None,
        "cutoff_utc": cutoff.isoformat(),
        "hot_retention_months": months,
        "batch_limit": max(1, lim),
        "runs_scanned": len(out_rows),
        "runs_updated": updated,
        "runs_with_broken_pointers": broken,
        "archive_storage_class": desired_sc,
        "rows": out_rows,
    }

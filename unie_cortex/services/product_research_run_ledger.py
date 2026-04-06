"""Canonical Product Research run ledger persistence and lineage helpers."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from unie_cortex.config import settings
from unie_cortex.db.store import CortexStore


SCHEMA_VERSION = "product_research_run_v1"

REQUIRED_COVERAGE_BLOCKS: tuple[str, ...] = (
    "monthly_forecast",
    "placements_us",
    "ltl_cms_expenses",
    "prep_services_economics",
    "allocation_rationale",
    "cuopt_artifacts",
)


def _json_dumps(v: Any) -> str:
    return json.dumps(v, sort_keys=True, separators=(",", ":"), default=str)


def sha256_json(v: Any) -> str:
    return hashlib.sha256(_json_dumps(v).encode("utf-8")).hexdigest()


def compute_rerun_key(
    *,
    tenant_id: str,
    warehouse_id: str,
    request_body: dict[str, Any],
) -> str:
    normalized = {
        "tenant_id": tenant_id.strip(),
        "warehouse_id": warehouse_id.strip(),
        "sku_filter": sorted([str(x).strip() for x in (request_body.get("sku_filter") or [])]),
        "warehouses": request_body.get("warehouses") or [],
        "lanes": request_body.get("lanes") or [],
        "hub_warehouse_id": request_body.get("hub_warehouse_id"),
        "product_origin_postal": request_body.get("product_origin_postal"),
        "product_origin_city": request_body.get("product_origin_city"),
        "product_origin_region": request_body.get("product_origin_region"),
        "free_delivery_policy_by_sku": request_body.get("free_delivery_policy_by_sku") or {},
        "free_delivery_policy_mapping": request_body.get("free_delivery_policy_mapping") or {},
        "engagement_id": request_body.get("engagement_id"),
    }
    return sha256_json(normalized)


def build_source_versions() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "item_intelligence_cuopt_overview_enabled": bool(
            getattr(settings, "item_intelligence_cuopt_overview_enabled", True)
        ),
        "item_intelligence_nvidia_cuopt_enabled": bool(
            getattr(settings, "item_intelligence_nvidia_cuopt_enabled", True)
        ),
        "product_research_keepa_refresh_hours": int(getattr(settings, "product_research_keepa_refresh_hours", 48) or 48),
        "product_research_rerun_update_days": int(getattr(settings, "product_research_rerun_update_days", 5) or 5),
        "product_research_hot_retention_months": int(
            getattr(settings, "product_research_hot_retention_months", 6) or 6
        ),
    }


def build_cache_lineage(*, run_request: dict[str, Any], artifact: dict[str, Any]) -> dict[str, Any]:
    keepa_hours = int(getattr(settings, "product_research_keepa_refresh_hours", 48) or 48)
    return {
        "schema_version": "product_research_cache_lineage_v1",
        "keepa_refresh_hours": keepa_hours,
        "keepa_requested_refresh": bool(run_request.get("refresh_keepa")),
        "keepa_errors_count": len(artifact.get("keepa_refresh_errors") or []),
        "keepa_refresh_errors": artifact.get("keepa_refresh_errors") or [],
        "demand_by_sku_cache_flags": {
            str(k): bool((v or {}).get("from_store"))
            for k, v in (artifact.get("demand_by_sku") or {}).items()
            if isinstance(v, dict)
        },
    }


def build_nvidia_lineage(artifact: dict[str, Any]) -> dict[str, Any]:
    tri = artifact.get("multi_dc_placement_tri_modal") if isinstance(
        artifact.get("multi_dc_placement_tri_modal"), dict
    ) else {}
    nvb = tri.get("nvidia_enhanced") if isinstance(tri.get("nvidia_enhanced"), dict) else {}
    req = nvb.get("request") if isinstance(nvb.get("request"), dict) else None
    res = nvb.get("response") if isinstance(nvb.get("response"), dict) else None
    status = str(nvb.get("status") or tri.get("status") or "unknown")
    mode = "skipped"
    if nvb:
        mode = "cloud_or_self_hosted"
    return {
        "schema_version": "product_research_nvidia_lineage_v1",
        "cuopt_provider": str(nvb.get("provider") or tri.get("solver_provider") or "n/a"),
        "cuopt_mode": mode,
        "solve_status": status,
        "cuopt_request_hash": sha256_json(req) if req is not None else None,
        "cuopt_response_hash": sha256_json(res) if res is not None else None,
        "job_ref": nvb.get("job_id") or nvb.get("job_ref"),
        "provider_response_metadata": nvb.get("provider_response_metadata") if isinstance(
            nvb.get("provider_response_metadata"), dict
        ) else None,
    }


def build_coverage(artifact: dict[str, Any]) -> dict[str, Any]:
    pre = artifact.get("product_research_economics")
    outputs = pre.get("outputs") if isinstance(pre, dict) and isinstance(pre.get("outputs"), dict) else {}
    coverage: dict[str, dict[str, Any]] = {}

    monthly_present = bool(artifact.get("demand_by_sku")) and bool(outputs)
    coverage["monthly_forecast"] = {"state": "saved_full" if monthly_present else "partial"}

    placements_present = isinstance(artifact.get("placement_mock_rate_grids"), dict) and isinstance(
        artifact.get("allocation"), dict
    )
    coverage["placements_us"] = {"state": "saved_full" if placements_present else "partial"}

    ltl_present = isinstance(artifact.get("distribution"), dict) or isinstance(
        artifact.get("facility_freight_by_warehouse_id"), dict
    )
    coverage["ltl_cms_expenses"] = {"state": "saved_full" if ltl_present else "partial"}

    prep_present = isinstance(outputs, dict) and bool(outputs)
    coverage["prep_services_economics"] = {"state": "saved_full" if prep_present else "partial"}

    alloc_present = isinstance(artifact.get("item_intelligence_synthesis"), dict) and isinstance(
        artifact.get("allocation"), dict
    )
    coverage["allocation_rationale"] = {"state": "saved_full" if alloc_present else "partial"}

    tri = artifact.get("multi_dc_placement_tri_modal")
    if isinstance(tri, dict):
        coverage["cuopt_artifacts"] = {"state": "saved_full"}
    else:
        coverage["cuopt_artifacts"] = {"state": "not_applicable", "reason": "cuopt_block_absent"}

    states = [str((coverage.get(k) or {}).get("state") or "") for k in REQUIRED_COVERAGE_BLOCKS]
    if any(s == "failed" for s in states):
        overall = "failed"
        reason_code = "coverage_failed"
    elif any(s == "partial" for s in states):
        overall = "partial"
        reason_code = "coverage_partial"
    elif any(s == "not_applicable" for s in states):
        overall = "partial"
        reason_code = "coverage_not_applicable"
    else:
        overall = "complete"
        reason_code = None
    return {
        "schema_version": "product_research_coverage_v1",
        "required_blocks": list(REQUIRED_COVERAGE_BLOCKS),
        "blocks": coverage,
        "overall_status": overall,
        "reason_code": reason_code,
    }


def build_routing_envelope(artifact: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "product_research_routing_envelope_v1",
        "distribution": artifact.get("distribution"),
        "recommended_warehouse_network": artifact.get("recommended_warehouse_network"),
        "warehouse_network_recommendation_options": artifact.get("warehouse_network_recommendation_options"),
        "item_intelligence_network": {
            "placement_mock_rate_grids": artifact.get("placement_mock_rate_grids"),
            "allocation": artifact.get("allocation"),
            "fulfillment_network_comparison": artifact.get("fulfillment_network_comparison"),
        },
    }


def should_force_rerun_refresh(latest: dict[str, Any] | None) -> bool:
    if latest is None:
        return True
    created_raw = latest.get("created_at")
    if not created_raw:
        return True
    created: datetime
    try:
        if isinstance(created_raw, datetime):
            created = created_raw
        else:
            created = datetime.fromisoformat(str(created_raw).replace("Z", "+00:00"))
    except ValueError:
        return True
    # SQLite / ORM rows may deserialize as naive datetimes; treat them as UTC.
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    else:
        created = created.astimezone(timezone.utc)
    days = int(getattr(settings, "product_research_rerun_update_days", 5) or 5)
    return datetime.now(timezone.utc) - created >= timedelta(days=max(1, days))


async def save_product_research_run_ledger(
    *,
    store: CortexStore,
    run_id: str,
    tenant_id: str,
    warehouse_id: str,
    engagement_id: str | None,
    job_id: str,
    request_body: dict[str, Any],
    artifact: dict[str, Any],
    artifact_s3_uri: str | None = None,
    distribution_s3_uri: str | None = None,
    cuopt_request_s3_uri: str | None = None,
    cuopt_response_s3_uri: str | None = None,
) -> dict[str, Any]:
    rerun_key = compute_rerun_key(tenant_id=tenant_id, warehouse_id=warehouse_id, request_body=request_body)
    latest = await store.product_research_run_latest_for_key(
        tenant_id=tenant_id,
        warehouse_id=warehouse_id,
        rerun_key=rerun_key,
    )
    coverage = build_coverage(artifact)
    cache_lineage = build_cache_lineage(run_request=request_body, artifact=artifact)
    nvidia = build_nvidia_lineage(artifact)
    routing = build_routing_envelope(artifact)
    source_versions = build_source_versions()
    status = str(coverage.get("overall_status") or "partial")
    reason = coverage.get("reason_code")
    now = datetime.now(timezone.utc)

    artifact_hash = sha256_json(artifact)
    dist = artifact.get("distribution") if isinstance(artifact.get("distribution"), dict) else None
    tri = artifact.get("multi_dc_placement_tri_modal") if isinstance(
        artifact.get("multi_dc_placement_tri_modal"), dict
    ) else {}
    nvb = tri.get("nvidia_enhanced") if isinstance(tri.get("nvidia_enhanced"), dict) else {}

    await store.product_research_run_upsert(
        {
            "id": run_id,
            "tenant_id": tenant_id,
            "warehouse_id": warehouse_id,
            "engagement_id": engagement_id,
            "job_id": job_id,
            "request_hash": rerun_key,
            "schema_version": SCHEMA_VERSION,
            "status": status,
            "status_reason_code": reason,
            "status_reason_detail": "Coverage evaluation for required Product Research blocks.",
            "source_versions_json": _json_dumps(source_versions),
            "cache_lineage_json": _json_dumps(cache_lineage),
            "coverage_json": _json_dumps(coverage),
            "routing_envelope_json": _json_dumps(routing),
            "nvidia_lineage_json": _json_dumps(nvidia),
            "request_json": _json_dumps(request_body),
            "artifact_json": _json_dumps(artifact),
            "artifact_sha256": artifact_hash,
            "artifact_s3_uri": artifact_s3_uri,
            "distribution_json": _json_dumps(dist) if dist is not None else None,
            "distribution_s3_uri": distribution_s3_uri,
            "cuopt_request_json": _json_dumps(nvb.get("request")) if nvb.get("request") is not None else None,
            "cuopt_response_json": _json_dumps(nvb.get("response")) if nvb.get("response") is not None else None,
            "cuopt_request_s3_uri": cuopt_request_s3_uri,
            "cuopt_response_s3_uri": cuopt_response_s3_uri,
            "created_at": now if latest is None else None,
            "completed_at": now,
        }
    )
    return {
        "rerun_key": rerun_key,
        "forced_refresh_due_to_age": should_force_rerun_refresh(latest),
        "coverage": coverage,
        "nvidia_lineage": nvidia,
        "source_versions": source_versions,
    }

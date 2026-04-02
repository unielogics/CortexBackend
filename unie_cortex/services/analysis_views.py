"""
Four default analytical views + MAIW input bundle (plan contract).

Maps: current | internal | internal_nvidia | nvidia_only ; pipeline_stages ; maiw_resources.
"""

from __future__ import annotations

from typing import Any


def build_maiw_resources(artifact: dict[str, Any]) -> dict[str, Any]:
    """Compact pack for MAIW last pass and nvidia_only from-scratch draft."""
    pmg = artifact.get("placement_mock_rate_grids") if isinstance(artifact, dict) else None
    pr = artifact.get("product_research_economics") if isinstance(artifact, dict) else None
    return {
        "schema_version": "maiw_resources_v1",
        "tenant_id": artifact.get("tenant_id"),
        "warehouse_id": artifact.get("warehouse_id"),
        "placement_mock_summary": {
            "status": (pmg or {}).get("status") if isinstance(pmg, dict) else None,
            "parcel_assumptions": (pmg or {}).get("parcel_assumptions") if isinstance(pmg, dict) else None,
        },
        "allocation_line_count": len((artifact.get("allocation") or {}).get("lines") or [])
        if isinstance(artifact.get("allocation"), dict)
        else None,
        "fulfillment_verdict": (artifact.get("fulfillment_network_comparison") or {}).get("verdict")
        if isinstance(artifact.get("fulfillment_network_comparison"), dict)
        else None,
        "product_research_outputs_requested": (
            ((pr or {}).get("assumptions") or {}).get("product_research_outputs_requested")
            if isinstance(pr, dict)
            else None
        ),
        "multi_dc_tri_modal_status": (artifact.get("multi_dc_placement_tri_modal") or {}).get("status")
        if isinstance(artifact.get("multi_dc_placement_tri_modal"), dict)
        else None,
        "sales_tax_modeling": (artifact.get("fulfillment_network_comparison") or {}).get("sales_tax_modeling")
        if isinstance(artifact.get("fulfillment_network_comparison"), dict)
        else None,
    }


def attach_four_views_and_pipeline(
    artifact: dict[str, Any],
    *,
    current_payload: dict[str, Any] | None = None,
    maiw_last: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Mutates artifact in place: adds views, meta.pipeline_stages, maiw_resources, optional maiw_last.
    """
    internal_core = {k: v for k, v in artifact.items() if k not in ("views", "meta", "maiw_resources", "maiw_last")}
    tri = artifact.get("multi_dc_placement_tri_modal")
    tri_ok = isinstance(tri, dict) and tri.get("status") not in (None, "skipped", "error")
    stages: list[dict[str, Any]] = [
        {"name": "ingest_deterministic", "status": "complete"},
        {"name": "internal_economics", "status": "complete"},
        {
            "name": "nim_llm",
            "status": "skipped",
            "note": "NIM narratives attach via audit narrative / MAIW query paths",
        },
        {
            "name": "cuopt",
            "status": "complete" if tri_ok else "skipped",
        },
        {"name": "maiw", "status": "complete" if maiw_last else "pending"},
    ]
    opt_enrich = (
        {
            "status": tri.get("status") if isinstance(tri, dict) else None,
            "nvidia_enhanced": tri.get("nvidia_enhanced") if isinstance(tri, dict) else None,
        }
        if isinstance(tri, dict)
        else {"status": "absent"}
    )
    pr = artifact.get("product_research_economics")
    internal_nvidia_overlay = {
        "internal_ref": "views.internal.payload",
        "nvidia_tri_modal": opt_enrich,
        "product_research_plus_nvidia": (pr or {}).get("outputs", {}).get("ours_plus_nvidia_enhancements")
        if isinstance(pr, dict)
        else None,
    }
    nvidia_only_draft = (pr or {}).get("outputs", {}).get("nvidia_only") if isinstance(pr, dict) else None

    artifact["views"] = {
        "current": current_payload
        or {
            "status": "skipped",
            "reason": "Item intelligence run; use assessment engagement + CSV for as-is current baseline.",
        },
        "internal": {"payload": internal_core},
        "internal_nvidia": {"payload": internal_core, "nvidia_overlay": internal_nvidia_overlay},
        "nvidia_only": nvidia_only_draft
        or {
            "status": "not_requested",
            "note": "Request product_research_outputs including nvidia_only to populate this slot.",
        },
    }
    artifact["meta"] = {
        "pipeline_stages": stages,
        "views_schema_version": "four_views_v1",
    }
    artifact["maiw_resources"] = build_maiw_resources(artifact)
    if maiw_last is not None:
        artifact["maiw_last"] = maiw_last
    return artifact

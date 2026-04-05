"""
Product research economics: four triggerable output surfaces (original, ours, ours+NVIDIA, NVIDIA-only).

v1 maps existing item-intelligence artifacts into the contract; FBA prep line-item breakdowns are future work.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Literal, cast

PRODUCT_RESEARCH_OUTPUT_KEYS: frozenset[str] = frozenset(
    ("original", "ours", "ours_plus_nvidia_enhancements", "nvidia_only")
)

ProductResearchOutputKey = Literal[
    "original",
    "ours",
    "ours_plus_nvidia_enhancements",
    "nvidia_only",
]

DEFAULT_PRODUCT_RESEARCH_OUTPUTS: tuple[ProductResearchOutputKey, ...] = ("original", "ours")


def normalize_product_research_outputs(
    requested: list[str] | None,
) -> list[ProductResearchOutputKey]:
    """
    Dedupe while preserving order. Empty list after filter defaults to DEFAULT_PRODUCT_RESEARCH_OUTPUTS.
    """
    if not requested:
        return list(DEFAULT_PRODUCT_RESEARCH_OUTPUTS)
    seen: set[str] = set()
    out: list[ProductResearchOutputKey] = []
    for x in requested:
        k = str(x).strip()
        if k not in PRODUCT_RESEARCH_OUTPUT_KEYS:
            raise ValueError(
                f"Invalid product_research_outputs entry {x!r}; "
                f"allowed: {sorted(PRODUCT_RESEARCH_OUTPUT_KEYS)}"
            )
        if k in seen:
            continue
        seen.add(k)
        out.append(cast(ProductResearchOutputKey, k))
    return out if out else list(DEFAULT_PRODUCT_RESEARCH_OUTPUTS)


def _json_fingerprint(obj: Any) -> str:
    raw = json.dumps(obj, sort_keys=True, default=str, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _slim_catalog_rows(catalog: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in catalog:
        sku = r.get("sku")
        if not sku:
            continue
        out.append(
            {
                "sku": sku,
                "asin": r.get("asin"),
                "weight_lb": r.get("weight_lb"),
                "length_in": r.get("length_in"),
                "width_in": r.get("width_in"),
                "height_in": r.get("height_in"),
                "physical_signature": r.get("physical_signature"),
            }
        )
    return out


def _placement_grids_summary(placement_mock_rate_grids: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(placement_mock_rate_grids, dict):
        return {"status": "absent"}
    return {
        "status": placement_mock_rate_grids.get("status"),
        "parcel_assumptions": placement_mock_rate_grids.get("parcel_assumptions"),
        "demand_weighting": placement_mock_rate_grids.get("demand_weighting"),
        "note": "Full per-warehouse mock grids live on the parent artifact under placement_mock_rate_grids.",
    }


def _rollup_tri_modal_ui_status(tri_modal: dict[str, Any]) -> str:
    """
    tri_modal from item intelligence usually has no root ``status``; we must not default to ``ok``,
    which implied NVIDIA succeeded. Surface nvidia_enhanced.status + source for the comparison UI.
    """
    root = tri_modal.get("status")
    if root:
        return str(root)
    nv = tri_modal.get("nvidia_enhanced")
    if not isinstance(nv, dict):
        return "tri_modal_present"
    st, src = nv.get("status"), nv.get("source")
    if st is None:
        return "tri_modal_present"
    if src:
        return f"{st}:{src}"
    return str(st)


def _optimization_enrichment_from_tri_modal(
    tri_modal: dict[str, Any] | None,
) -> dict[str, Any]:
    if not tri_modal:
        return {
            "status": "skipped",
            "message": "multi_dc_placement_tri_modal was not produced for this run (disabled or no warehouses).",
        }
    return {
        "status": _rollup_tri_modal_ui_status(tri_modal),
        "schema_version": tri_modal.get("schema_version"),
        "original_input": tri_modal.get("original_input"),
        "solver_inputs_original_vs_enhanced": tri_modal.get("solver_inputs_original_vs_enhanced"),
        "microscopic_placement_expenses": tri_modal.get("microscopic_placement_expenses"),
        "cuopt_fusion_audit": tri_modal.get("cuopt_fusion_audit"),
        "cuopt_enrichment_analysis": tri_modal.get("cuopt_enrichment_analysis"),
        "baseline_without_nvidia": tri_modal.get("baseline_without_nvidia"),
        "nvidia_enhanced": tri_modal.get("nvidia_enhanced"),
        "eligibility": tri_modal.get("eligibility"),
        "note": tri_modal.get("note"),
        "does_not_replace_outputs_ours": True,
    }


def _nvidia_supplemental_layers(
    optimization_enrichment: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Structured NVIDIA/cuOpt parts + parallel narrative placeholder (comparison UI only)."""
    parts = {
        "optimization_enrichment": optimization_enrichment,
        "nim_enhancement": None,
    }
    parallel = {
        "status": "not_generated_v1",
        "purpose": "comparison_ui_only",
        "message": "Reserved for from-scratch NIM narrative; not billing truth.",
    }
    return parts, parallel


def _build_outputs_ours(
    *,
    allocation: dict[str, Any],
    landed_cost_economics: dict[str, Any],
    fulfillment_network_comparison: dict[str, Any],
    item_intelligence_synthesis: dict[str, Any],
    product_research_core: dict[str, Any] | None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "schema_version": "product_research_economics_ours_v1",
        "allocation": allocation,
        "landed_cost_economics": landed_cost_economics,
        "fulfillment_network_comparison": fulfillment_network_comparison,
        "item_intelligence_synthesis": item_intelligence_synthesis,
        "note": (
            "Authoritative Cortex bundle for this run (NVIDIA-free). "
            "Includes FBA prep + FBM breakdowns and Amazon fee estimates when product research is enabled."
        ),
    }
    if product_research_core:
        out["fba_prep_services_breakdown"] = product_research_core["fba_prep_services_breakdown"]
        out["amazon_fees_live"] = product_research_core["amazon_fees_live"]
        out["product_research_by_sku"] = product_research_core["per_sku"]
        out["product_research_core_schema_version"] = product_research_core["schema_version"]
        out["schema_version"] = "product_research_economics_ours_v2"
    return out


def _build_outputs_original(
    *,
    tenant_id: str,
    operational_warehouse_id: str,
    request_echo: dict[str, Any],
    catalog_slim: list[dict[str, Any]],
    demand_by_sku: dict[str, Any],
    placement_summary: dict[str, Any],
    placement_allocation_share_source: Any,
    upc_catalog_search: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "schema_version": "product_research_economics_original_v1",
        "tenant_id": tenant_id,
        "operational_warehouse_id": operational_warehouse_id,
        "request_context": request_echo,
        "catalog_slim": catalog_slim,
        "demand_by_sku": demand_by_sku,
        "placement_mock_rate_grids_summary": placement_summary,
        "placement_allocation_share_source": placement_allocation_share_source,
        "upc_catalog_search": upc_catalog_search,
        "note": (
            "Inputs and external-facing extracts before Unie-assembled line-item prep/FBM product-research sheets; "
            "see outputs.ours for assembled economics."
        ),
    }


def build_product_research_economics(
    *,
    tenant_id: str,
    operational_warehouse_id: str,
    request_echo: dict[str, Any],
    catalog: list[dict[str, Any]],
    demand_by_sku: dict[str, Any],
    placement_mock_rate_grids: dict[str, Any] | None,
    placement_allocation_share_source: Any,
    allocation: dict[str, Any],
    landed_cost_economics: dict[str, Any],
    fulfillment_network_comparison: dict[str, Any],
    item_intelligence_synthesis: dict[str, Any],
    multi_dc_placement_tri_modal: dict[str, Any] | None,
    requested_outputs: list[ProductResearchOutputKey],
    product_research_core: dict[str, Any] | None = None,
    upc_catalog_search: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Assemble the four output slots. Keys not requested are set to None.
    """
    wanted = set(requested_outputs)
    need_ours_core = bool(
        wanted & {"ours", "ours_plus_nvidia_enhancements", "nvidia_only"}
    )

    ours_block: dict[str, Any] | None = None
    if need_ours_core:
        ours_block = _build_outputs_ours(
            allocation=allocation,
            landed_cost_economics=landed_cost_economics,
            fulfillment_network_comparison=fulfillment_network_comparison,
            item_intelligence_synthesis=item_intelligence_synthesis,
            product_research_core=product_research_core,
        )

    opt_enrich = _optimization_enrichment_from_tri_modal(multi_dc_placement_tri_modal)
    nvidia_parts, nvidia_parallel = _nvidia_supplemental_layers(opt_enrich)
    fingerprint = _json_fingerprint(ours_block) if ours_block is not None else None

    out_original: dict[str, Any] | None = None
    if "original" in wanted:
        out_original = _build_outputs_original(
            tenant_id=tenant_id,
            operational_warehouse_id=operational_warehouse_id,
            request_echo=request_echo,
            catalog_slim=_slim_catalog_rows(catalog),
            demand_by_sku=demand_by_sku,
            placement_summary=_placement_grids_summary(placement_mock_rate_grids),
            placement_allocation_share_source=placement_allocation_share_source,
            upc_catalog_search=upc_catalog_search,
        )

    out_ours: dict[str, Any] | None = ours_block if "ours" in wanted else None

    out_plus: dict[str, Any] | None = None
    if "ours_plus_nvidia_enhancements" in wanted:
        base = copy.deepcopy(ours_block) if ours_block else _build_outputs_ours(
            allocation=allocation,
            landed_cost_economics=landed_cost_economics,
            fulfillment_network_comparison=fulfillment_network_comparison,
            item_intelligence_synthesis=item_intelligence_synthesis,
            product_research_core=product_research_core,
        )
        out_plus = {
            **base,
            "schema_version": "product_research_economics_ours_plus_nvidia_v1",
            "optimization_enrichment": opt_enrich,
            "nvidia_enhancement_parts": nvidia_parts,
            "nim_enhancement": None,
            "nvidia_parallel_narrative": nvidia_parallel,
            "note": (
                "Convenience merge: same economics as outputs.ours plus NVIDIA/cuOpt enrichment. "
                "Does not replace outputs.ours; nim_enhancement is reserved and always null (no hosted LLM)."
            ),
        }

    out_nvidia: dict[str, Any] | None = None
    if "nvidia_only" in wanted:
        out_nvidia = {
            "schema_version": "product_research_economics_nvidia_only_v1",
            "purpose": "nvidia_supplemental_only",
            "references_outputs_ours": True,
            "fingerprint_of_ours": fingerprint,
            "optimization_enrichment": opt_enrich,
            "nvidia_enhancement_parts": nvidia_parts,
            "nim_enhancement": None,
            "nvidia_parallel_narrative": nvidia_parallel,
            "comparison_ui_only_note": (
                "When nvidia_parallel_narrative is populated, use for comparison UI only—not billing."
            ),
        }

    return {
        "schema_version": "product_research_economics_v1",
        "assumptions": {
            "tenant_id": tenant_id,
            "operational_warehouse_id": operational_warehouse_id,
            "product_research_outputs_requested": list(requested_outputs),
        },
        "outputs": {
            "original": out_original,
            "ours": out_ours,
            "ours_plus_nvidia_enhancements": out_plus,
            "nvidia_only": out_nvidia,
        },
    }

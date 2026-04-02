"""Compact item-intelligence extract for diff-friendly JSON artifacts (demos, CI)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def extract_product_research_fba_fbm_for_sku(
    item_intel: dict[str, Any] | None,
    sku: str,
) -> dict[str, Any] | None:
    """
    Pull FBA prep breakdown, FBM line breakdown, and FBA vs FBM scenario comparison for one SKU
    from ``product_research_economics.outputs.ours`` (when present).
    """
    if not isinstance(item_intel, dict):
        return None
    pre = item_intel.get("product_research_economics")
    if not isinstance(pre, dict):
        return None
    outs = pre.get("outputs")
    if not isinstance(outs, dict):
        return None
    ours = outs.get("ours")
    if not isinstance(ours, dict):
        return None
    rows = ours.get("product_research_by_sku") or []
    row = next((r for r in rows if isinstance(r, dict) and r.get("sku") == sku), None)
    amz = ours.get("amazon_fees_live") if isinstance(ours.get("amazon_fees_live"), dict) else {}
    return {
        "schema_version": "product_research_fba_fbm_slim_v1",
        "sku": sku,
        "fba_prep_services_breakdown": ours.get("fba_prep_services_breakdown"),
        "fbm_fulfillment_services_breakdown": (row or {}).get("fbm_fulfillment_services_breakdown"),
        "scenarios_comparison": (row or {}).get("scenarios", {}).get("comparison"),
        "amazon_fees_live": {
            "status": amz.get("status"),
            "message": amz.get("message"),
        },
    }


def build_item_intel_slim_artifact(
    item_intel: dict[str, Any] | None,
    *,
    meta: dict[str, Any] | None = None,
    include_generated_at: bool = False,
) -> dict[str, Any] | None:
    """
    Returns a small dict with synthesis bullets and facility freight, or None if ``item_intel`` is missing.

    ``meta`` is optional (e.g. tenant_id, sku, script name) — merged under ``meta`` key.
    ``include_generated_at``: when True, adds ``generated_at_utc`` (turn off for stable golden-file diffs).
    """
    if not isinstance(item_intel, dict):
        return None
    syn = item_intel.get("item_intelligence_synthesis") or {}
    out: dict[str, Any] = {
        "schema_version": "item_intel_slim_v1",
        "run_summary_bullets": syn.get("run_summary_bullets"),
        "facility_freight_by_warehouse_id": item_intel.get("facility_freight_by_warehouse_id"),
    }
    if include_generated_at:
        out["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
    if meta:
        out["meta"] = {k: v for k, v in meta.items() if v is not None}
    sku = (meta or {}).get("sku") if meta else None
    if sku:
        pr = extract_product_research_fba_fbm_for_sku(item_intel, str(sku))
        if pr is not None:
            out["product_research_fba_fbm"] = pr
    return out


def write_item_intel_slim_json(path: str | Path, payload: dict[str, Any]) -> None:
    """Write ``payload`` with stable key order for line-based diffs."""
    import json

    p = Path(path)
    text = json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n"
    p.write_text(text, encoding="utf-8")

"""Optional spine module: SKU-level velocity from label/task facts."""

from __future__ import annotations

from unie_cortex.db.store import CortexStore
from unie_cortex.services.velocity_rollup import rollup_velocity


async def analyze_sku_velocity(
    store: CortexStore,
    engagement_id: str | None,
    tenant_id: str | None,
    warehouse_id: str | None,
    status: str,
    missing: list[str],
) -> dict:
    if status == "skipped":
        return {
            "status": "skipped",
            "missing_fields": missing,
            "message": "Map sku on label CSV columns (or task sku) to enable SKU velocity.",
        }

    labels = await store.label_facts_list(
        engagement_id=engagement_id,
        tenant_id=tenant_id,
        warehouse_id=warehouse_id,
    )
    tasks = await store.task_facts_list(
        engagement_id=engagement_id,
        tenant_id=tenant_id,
        warehouse_id=warehouse_id,
    )
    rollup = rollup_velocity(labels, tasks, warehouse_id=warehouse_id)
    if rollup.get("sku_count", 0) == 0:
        return {
            "status": "partial" if status == "partial" else "skipped",
            "message": "No sku populated on facts yet.",
            "by_sku": [],
        }
    top = sorted(
        rollup.get("by_sku") or [],
        key=lambda x: -x.get("label_lines", 0) - x.get("task_touches", 0),
    )[:15]
    return {
        "status": status,
        "warehouse_id": warehouse_id,
        "sku_count": rollup.get("sku_count"),
        "top_skus": top,
        "by_sku": rollup.get("by_sku"),
    }

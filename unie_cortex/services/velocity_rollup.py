"""Aggregate SKU velocity from label and task facts."""

from __future__ import annotations

from collections import defaultdict
from typing import Any


def rollup_velocity(
    label_rows: list[dict[str, Any]],
    task_rows: list[dict[str, Any]],
    *,
    warehouse_id: str | None = None,
) -> dict[str, Any]:
    """
    Per-SKU counts: label lines, shipped qty sum, task touches.
    If warehouse_id set, filter rows to that warehouse.
    """
    lf = label_rows
    tf = task_rows
    if warehouse_id:
        lf = [r for r in lf if (r.get("warehouse_id") or "") == warehouse_id]
        tf = [r for r in tf if (r.get("warehouse_id") or "") == warehouse_id]

    by_sku_labels: dict[str, int] = defaultdict(int)
    qty_by_sku: dict[str, float] = defaultdict(float)
    by_sku_tasks: dict[str, int] = defaultdict(int)

    for r in lf:
        sku = (r.get("sku") or "").strip()
        if not sku:
            continue
        by_sku_labels[sku] += 1
        q = r.get("qty")
        if q is not None:
            try:
                qty_by_sku[sku] += float(q)
            except (TypeError, ValueError):
                pass

    for r in tf:
        sku = (r.get("sku") or "").strip()
        if not sku:
            continue
        by_sku_tasks[sku] += 1

    skus = sorted(set(by_sku_labels) | set(by_sku_tasks.keys()) | set(qty_by_sku.keys()))
    rows = []
    for sku in skus:
        rows.append(
            {
                "sku": sku,
                "label_lines": by_sku_labels.get(sku, 0),
                "qty_shipped_sum": round(qty_by_sku.get(sku, 0.0), 4),
                "task_touches": by_sku_tasks.get(sku, 0),
            }
        )

    return {
        "warehouse_id": warehouse_id,
        "sku_count": len(rows),
        "by_sku": rows,
    }

"""Operator × task_type performance from task facts (WMS labor intelligence)."""

from __future__ import annotations

import statistics
from collections import defaultdict
from typing import Any


def analyze_operator_tasks(task_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Median duration by (operator_id, task_type); best operator per task_type by median sec.
    Rows need operator_id, task_type, duration_sec (optional completed_at for volume only).
    """
    dur_key: dict[tuple[str, str], list[float]] = defaultdict(list)
    volume: dict[tuple[str, str], int] = defaultdict(int)

    for row in task_rows:
        op = row.get("operator_id")
        tt = row.get("task_type") or "unknown"
        if not op:
            continue
        volume[(op, tt)] += 1
        ds = row.get("duration_sec")
        if ds is not None:
            try:
                dur_key[(op, tt)].append(float(ds))
            except (TypeError, ValueError):
                pass

    by_pair: list[dict[str, Any]] = []
    for (op, tt), durs in dur_key.items():
        med = statistics.median(durs) if durs else None
        by_pair.append(
            {
                "operator_id": op,
                "task_type": tt,
                "task_count": volume[(op, tt)],
                "duration_samples": len(durs),
                "median_duration_sec": round(med, 2) if med is not None else None,
            }
        )

    by_task: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in by_pair:
        if item["median_duration_sec"] is not None:
            by_task[item["task_type"]].append(item)

    best_for_task: dict[str, Any] = {}
    for tt, items in by_task.items():
        winner = min(items, key=lambda x: x["median_duration_sec"])
        best_for_task[tt] = {
            "best_operator_id": winner["operator_id"],
            "median_duration_sec": winner["median_duration_sec"],
            "task_count": winner["task_count"],
        }

    return {
        "status": "complete",
        "operator_task_rows": len(task_rows),
        "pairs_with_duration": len(by_pair),
        "by_operator_task": sorted(by_pair, key=lambda x: (x["task_type"], x["operator_id"])),
        "best_operator_by_task_type": best_for_task,
        "notes": "Prefer routing tasks to best_operator_by_task_type when WMS rules allow; validate sample sizes.",
    }

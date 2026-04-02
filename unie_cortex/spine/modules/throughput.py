from collections import defaultdict

from unie_cortex.db.store import CortexStore
from unie_cortex.integrations.benchmarks import labor_benchmark_context


async def analyze_throughput(
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
            "message": "Insufficient data for throughput module (need completed_at + zone).",
        }

    rows = await store.task_facts_list(
        engagement_id=engagement_id,
        tenant_id=tenant_id,
        warehouse_id=warehouse_id,
    )
    if not rows:
        return {"status": "skipped", "message": "No task rows."}

    by_hour: dict[str, int] = defaultdict(int)
    by_zone: dict[str, int] = defaultdict(int)
    for t in rows:
        z = t.get("zone")
        if z:
            by_zone[z] += 1
        ca = t.get("completed_at")
        if ca:
            h = str(ca)[:13] if len(str(ca)) >= 13 else "unknown"
            by_hour[h] += 1

    total_tasks = len(rows)
    peak_hour = max(by_hour.items(), key=lambda x: x[1]) if by_hour else ("n/a", 0)
    peak_zone = max(by_zone.items(), key=lambda x: x[1]) if by_zone else ("n/a", 0)
    hours = len(by_hour) or 1
    picks_per_hour = total_tasks / hours

    bottleneck_zones = sorted(by_zone.items(), key=lambda x: -x[1])[:5]
    return {
        "status": status,
        "total_tasks": total_tasks,
        "tasks_by_hour_bucket": dict(sorted(by_hour.items())[:48]),
        "tasks_by_zone": dict(by_zone),
        "peak_hour_bucket": peak_hour[0],
        "peak_hour_count": peak_hour[1],
        "heaviest_zone": peak_zone[0],
        "heaviest_zone_count": peak_zone[1],
        "estimated_tasks_per_hour": round(picks_per_hour, 2),
        "bottleneck_zones_top5": [{"zone": z, "count": c} for z, c in bottleneck_zones],
        "labor_benchmark": labor_benchmark_context(picks_per_hour),
    }

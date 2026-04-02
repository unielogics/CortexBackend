from unie_cortex.db.store import CortexStore
from unie_cortex.integrations.rate_shopping import RateShoppingService


async def analyze_label_cost(
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
            "message": "Insufficient data for label cost module.",
        }

    rows = await store.label_facts_list(
        engagement_id=engagement_id,
        tenant_id=tenant_id,
        warehouse_id=warehouse_id,
    )
    if not rows:
        return {
            "status": "skipped",
            "message": "No label rows ingested.",
        }

    rs = RateShoppingService()
    total_actual = 0.0
    total_benchmark = 0.0
    n = 0
    for lf in rows:
        amt = lf.get("label_amount_usd")
        if amt is None:
            continue
        w = lf.get("weight_lb") or 1.0
        est, _ = await rs.quote_usd(
            float(w),
            lf.get("origin_postal"),
            lf.get("dest_postal"),
            lf.get("service_code"),
        )
        total_actual += float(amt)
        total_benchmark += est
        n += 1

    if n == 0:
        return {"status": "partial", "message": "No rows with label_amount_usd."}

    delta = total_actual - total_benchmark
    low = max(0.0, delta * 0.7)
    high = max(0.0, delta * 1.15)
    return {
        "status": status,
        "row_count": n,
        "total_actual_usd": round(total_actual, 2),
        "total_benchmark_usd": round(total_benchmark, 2),
        "delta_usd": round(delta, 2),
        "opportunity_if_shopped_usd": {
            "low": round(low, 2),
            "high": round(high, 2),
            "note": "Benchmark from internal heuristic or external rate API; not a guarantee.",
        },
    }

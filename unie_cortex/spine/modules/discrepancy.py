from collections import Counter

from unie_cortex.db.store import CortexStore


async def analyze_discrepancies(
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
            "findings": [],
        }

    rows = await store.label_facts_list(
        engagement_id=engagement_id,
        tenant_id=tenant_id,
        warehouse_id=warehouse_id,
    )

    findings: list[dict] = []
    tracks = [r.get("tracking_number") for r in rows if r.get("tracking_number")]
    dup = [t for t, c in Counter(tracks).items() if c > 1]
    if dup:
        findings.append(
            {
                "type": "duplicate_tracking",
                "severity": "high",
                "count": len(dup),
                "sample": dup[:10],
                "message": "Duplicate tracking numbers may indicate rebills or data quality issues.",
            }
        )

    neg = [r for r in rows if r.get("label_amount_usd") is not None and r["label_amount_usd"] < 0]
    if neg:
        findings.append(
            {
                "type": "negative_label_amount",
                "severity": "medium",
                "count": len(neg),
                "message": "Negative label amounts warrant billing review.",
            }
        )

    high = [r for r in rows if r.get("label_amount_usd") is not None and r["label_amount_usd"] > 500]
    if high:
        findings.append(
            {
                "type": "high_value_shipments",
                "severity": "low",
                "count": len(high),
                "message": "Unusually high single-label spend; validate service level and dim weight.",
            }
        )

    missing_dest = sum(1 for r in rows if not r.get("dest_postal"))
    if rows and missing_dest / len(rows) > 0.1:
        findings.append(
            {
                "type": "missing_destination",
                "severity": "medium",
                "pct": round(100 * missing_dest / len(rows), 1),
                "message": "Many rows lack destination postal — limits zone-based savings analysis.",
            }
        )

    return {
        "status": status if findings or status == "complete" else "partial",
        "findings": findings,
        "rows_scanned": len(rows),
    }

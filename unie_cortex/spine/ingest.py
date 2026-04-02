"""CSV ingest -> CortexStore (Mongo or SQL)."""

import csv
import io
from typing import Any
from uuid import uuid4

from unie_cortex.db.store import CortexStore
from unie_cortex.services.engagement_warehouse import match_origin_postal_to_warehouse_id

CANONICAL_LABEL = {
    "tracking_number",
    "carrier",
    "service_code",
    "label_amount_usd",
    "weight_lb",
    "origin_postal",
    "dest_postal",
    "ship_date",
    "sku",
    "qty",
    "line_amount_usd",
}
CANONICAL_TASK = {
    "completed_at",
    "zone",
    "operator_id",
    "task_type",
    "duration_sec",
    "sku",
}


def _parse_float(val: Any) -> float | None:
    if val is None or val == "":
        return None
    try:
        return float(str(val).replace("$", "").replace(",", "").strip())
    except ValueError:
        return None


def _row_to_canonical(row: dict[str, str], mappings: dict[str, str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for src, dest in mappings.items():
        if src not in row:
            continue
        raw = row.get(src, "")
        if dest == "label_amount_usd":
            out[dest] = _parse_float(raw)
        elif dest == "weight_lb":
            out[dest] = _parse_float(raw)
        elif dest == "qty":
            out[dest] = _parse_float(raw)
        elif dest == "line_amount_usd":
            out[dest] = _parse_float(raw)
        elif dest == "duration_sec":
            out[dest] = _parse_float(raw)
        else:
            out[dest] = (raw or None) if isinstance(raw, str) else raw
    return out


async def ingest_labels_csv(
    store: CortexStore,
    engagement_id: str,
    file_content: bytes,
    filename: str,
    mappings: dict[str, str],
    *,
    candidate_warehouses: list[dict[str, Any]] | None = None,
) -> tuple[str, int]:
    text = file_content.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
    batch_id = str(uuid4())
    facts: list[dict] = []
    for r in rows:
        c = _row_to_canonical({k or "": v for k, v in r.items()}, mappings)
        if not any(c.get(f) is not None for f in CANONICAL_LABEL if f in c):
            continue
        wh_id = match_origin_postal_to_warehouse_id(c.get("origin_postal"), candidate_warehouses)
        facts.append(
            {
                "engagement_id": engagement_id,
                "batch_id": batch_id,
                "tenant_id": None,
                "warehouse_id": wh_id,
                "tracking_number": c.get("tracking_number"),
                "carrier": c.get("carrier"),
                "service_code": c.get("service_code"),
                "label_amount_usd": c.get("label_amount_usd"),
                "weight_lb": c.get("weight_lb"),
                "origin_postal": c.get("origin_postal"),
                "dest_postal": c.get("dest_postal"),
                "ship_date": c.get("ship_date"),
                "sku": c.get("sku"),
                "qty": c.get("qty"),
                "line_amount_usd": c.get("line_amount_usd"),
            }
        )
    await store.label_facts_insert(facts)
    return batch_id, len(facts)


async def ingest_tasks_csv(
    store: CortexStore,
    engagement_id: str,
    file_content: bytes,
    filename: str,
    mappings: dict[str, str],
) -> tuple[str, int]:
    text = file_content.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
    batch_id = str(uuid4())
    facts: list[dict] = []
    for r in rows:
        c = _row_to_canonical({k or "": v for k, v in r.items()}, mappings)
        if not c.get("completed_at") and not c.get("zone"):
            continue
        facts.append(
            {
                "engagement_id": engagement_id,
                "batch_id": batch_id,
                "tenant_id": None,
                "warehouse_id": None,
                "completed_at": c.get("completed_at"),
                "zone": c.get("zone"),
                "operator_id": c.get("operator_id"),
                "task_type": c.get("task_type"),
                "duration_sec": c.get("duration_sec"),
                "sku": c.get("sku"),
            }
        )
    await store.task_facts_insert(facts)
    return batch_id, len(facts)

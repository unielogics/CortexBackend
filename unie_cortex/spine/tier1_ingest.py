"""CSV ingest for assessment tier-1 facts: ASN, order lines, billing, employees."""

from __future__ import annotations

import csv
import io
from typing import Any
from uuid import uuid4

from unie_cortex.db.store import CortexStore
from unie_cortex.spine.ingest import _parse_float

CANONICAL_ASN = frozenset(
    {
        "asn_line_id",
        "po_id",
        "sku",
        "qty_expected",
        "qty_received",
        "expected_at_iso",
        "received_at_iso",
        "supplier_id",
        "dock_zone",
    }
)
CANONICAL_ORDER_LINE = frozenset(
    {
        "order_external_id",
        "line_id",
        "sku",
        "quantity",
        "ordered_at_iso",
        "shipped_at_iso",
        "ship_to_postal",
        "channel",
    }
)
CANONICAL_BILLING = frozenset(
    {
        "invoice_id",
        "line_id",
        "fee_code",
        "service_start_iso",
        "service_end_iso",
        "amount_usd",
        "currency",
    }
)
CANONICAL_EMPLOYEE = frozenset(
    {
        "employee_id",
        "role",
        "hire_date_iso",
        "shift_name",
        "hourly_rate_usd",
    }
)

_ASN_FLOATS = frozenset({"qty_expected", "qty_received"})
_OL_FLOATS = frozenset({"quantity"})
_BL_FLOATS = frozenset({"amount_usd"})
_EM_FLOATS = frozenset({"hourly_rate_usd"})


def _row_map(
    row: dict[str, str],
    mappings: dict[str, str],
    allowed: frozenset[str],
    float_fields: frozenset[str],
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    norm = {k or "": v for k, v in row.items()}
    for src, dest in mappings.items():
        if dest not in allowed:
            continue
        if src not in norm:
            continue
        raw = norm.get(src, "")
        if dest in float_fields:
            out[dest] = _parse_float(raw)
        else:
            s = raw if isinstance(raw, str) else str(raw or "")
            out[dest] = s.strip() or None
    return out


def _asn_row_ok(c: dict[str, Any]) -> bool:
    if c.get("asn_line_id"):
        return True
    return bool(c.get("sku") and (c.get("received_at_iso") or c.get("expected_at_iso")))


def _ol_row_ok(c: dict[str, Any]) -> bool:
    return bool(c.get("order_external_id") or c.get("line_id")) and bool(
        c.get("sku") or c.get("shipped_at_iso") or c.get("ordered_at_iso")
    )


def _bl_row_ok(c: dict[str, Any]) -> bool:
    return bool(c.get("invoice_id") or c.get("line_id"))


def _em_row_ok(c: dict[str, Any]) -> bool:
    return bool(c.get("employee_id"))


async def ingest_asn_csv(
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
        c = _row_map(r, mappings, CANONICAL_ASN, _ASN_FLOATS)
        if not _asn_row_ok(c):
            continue
        facts.append(
            {
                "engagement_id": engagement_id,
                "batch_id": batch_id,
                **{k: c.get(k) for k in CANONICAL_ASN},
                "extra": None,
            }
        )
    await store.asn_facts_insert(facts)
    return batch_id, len(facts)


async def ingest_order_lines_csv(
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
        c = _row_map(r, mappings, CANONICAL_ORDER_LINE, _OL_FLOATS)
        if not _ol_row_ok(c):
            continue
        facts.append(
            {
                "engagement_id": engagement_id,
                "batch_id": batch_id,
                **{k: c.get(k) for k in CANONICAL_ORDER_LINE},
                "extra": None,
            }
        )
    await store.order_line_facts_insert(facts)
    return batch_id, len(facts)


async def ingest_billing_lines_csv(
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
        c = _row_map(r, mappings, CANONICAL_BILLING, _BL_FLOATS)
        if not _bl_row_ok(c):
            continue
        facts.append(
            {
                "engagement_id": engagement_id,
                "batch_id": batch_id,
                **{k: c.get(k) for k in CANONICAL_BILLING},
                "extra": None,
            }
        )
    await store.billing_line_facts_insert(facts)
    return batch_id, len(facts)


async def ingest_employees_csv(
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
        c = _row_map(r, mappings, CANONICAL_EMPLOYEE, _EM_FLOATS)
        if not _em_row_ok(c):
            continue
        facts.append(
            {
                "engagement_id": engagement_id,
                "batch_id": batch_id,
                **{k: c.get(k) for k in CANONICAL_EMPLOYEE},
                "extra": None,
            }
        )
    await store.employee_facts_insert(facts)
    return batch_id, len(facts)

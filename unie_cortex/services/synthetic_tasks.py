"""Derive assessment task_facts from ASN + order_line facts when no uploaded tasks exist."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from unie_cortex.db.store import CortexStore


def _is_synthetic_task(row: dict[str, Any]) -> bool:
    ex = row.get("extra")
    return isinstance(ex, dict) and ex.get("provenance") == "synthetic"


def _non_synthetic_task_count(tasks: list[dict[str, Any]]) -> int:
    return sum(1 for t in tasks if not _is_synthetic_task(t))


async def ensure_synthetic_tasks_from_tier1(store: CortexStore, engagement_id: str) -> dict[str, Any]:
    """
    If the engagement has no uploaded (non-synthetic) tasks but has ASN and/or order lines,
    replace prior synthetic tasks and insert new ones with strict provenance in extra.
    """
    tasks = await store.task_facts_list(engagement_id=engagement_id)
    if _non_synthetic_task_count(tasks) > 0:
        return {"skipped": True, "reason": "uploaded_tasks_present", "deleted": 0, "inserted": 0}

    asn_rows = await store.asn_facts_list(engagement_id)
    ol_rows = await store.order_line_facts_list(engagement_id)
    if not asn_rows and not ol_rows:
        return {"skipped": True, "reason": "no_asn_or_order_lines", "deleted": 0, "inserted": 0}

    deleted = await store.task_facts_delete_synthetic_for_engagement(engagement_id)
    batch_id = str(uuid4())
    out_rows: list[dict[str, Any]] = []

    for a in asn_rows:
        ts = a.get("received_at_iso") or a.get("expected_at_iso")
        if not ts or not str(ts).strip():
            continue
        zone = (a.get("dock_zone") or "RECV").strip() or "RECV"
        sku = a.get("sku")
        qty = a.get("qty_received") if a.get("qty_received") is not None else a.get("qty_expected")
        extra = {
            "provenance": "synthetic",
            "synthesis_rule": "asn_receipt",
            "source_fact": "asn",
            "source_keys": {
                "asn_line_id": a.get("asn_line_id"),
                "po_id": a.get("po_id"),
                "batch_id": a.get("batch_id"),
            },
            "qty_observed": qty,
        }
        out_rows.append(
            {
                "engagement_id": engagement_id,
                "batch_id": batch_id,
                "tenant_id": None,
                "warehouse_id": None,
                "completed_at": str(ts).strip(),
                "zone": zone,
                "operator_id": None,
                "task_type": "receive",
                "duration_sec": None,
                "sku": sku,
                "extra": extra,
            }
        )

    for o in ol_rows:
        sku = o.get("sku")
        ship_ts = o.get("shipped_at_iso")
        ord_ts = o.get("ordered_at_iso")
        if ship_ts and str(ship_ts).strip():
            ts = str(ship_ts).strip()
            rule = "order_ship"
            ttype = "ship"
        elif ord_ts and str(ord_ts).strip():
            ts = str(ord_ts).strip()
            rule = "order_pick"
            ttype = "pick"
        else:
            continue
        extra = {
            "provenance": "synthetic",
            "synthesis_rule": rule,
            "source_fact": "order_line",
            "source_keys": {
                "order_external_id": o.get("order_external_id"),
                "line_id": o.get("line_id"),
                "batch_id": o.get("batch_id"),
            },
            "ship_to_postal": o.get("ship_to_postal"),
            "channel": o.get("channel"),
        }
        out_rows.append(
            {
                "engagement_id": engagement_id,
                "batch_id": batch_id,
                "tenant_id": None,
                "warehouse_id": None,
                "completed_at": ts,
                "zone": "SHIP" if ttype == "ship" else "PICK",
                "operator_id": None,
                "task_type": ttype,
                "duration_sec": None,
                "sku": sku,
                "extra": extra,
            }
        )

    if out_rows:
        await store.task_facts_insert(out_rows)

    return {
        "skipped": False,
        "reason": None,
        "deleted": deleted,
        "inserted": len(out_rows),
        "synthetic_batch_id": batch_id,
    }


async def rebuild_synthetic_tasks_from_tier1(store: CortexStore, engagement_id: str) -> dict[str, Any]:
    """Always drop synthetic tasks and rebuild from current ASN + order_line facts (uploaded tasks untouched)."""
    asn_rows = await store.asn_facts_list(engagement_id)
    ol_rows = await store.order_line_facts_list(engagement_id)
    deleted = await store.task_facts_delete_synthetic_for_engagement(engagement_id)
    if not asn_rows and not ol_rows:
        return {"deleted": deleted, "inserted": 0, "synthetic_batch_id": None, "warning": "no_asn_or_order_lines"}

    batch_id = str(uuid4())
    out_rows: list[dict[str, Any]] = []

    for a in asn_rows:
        ts = a.get("received_at_iso") or a.get("expected_at_iso")
        if not ts or not str(ts).strip():
            continue
        zone = (a.get("dock_zone") or "RECV").strip() or "RECV"
        sku = a.get("sku")
        qty = a.get("qty_received") if a.get("qty_received") is not None else a.get("qty_expected")
        out_rows.append(
            {
                "engagement_id": engagement_id,
                "batch_id": batch_id,
                "tenant_id": None,
                "warehouse_id": None,
                "completed_at": str(ts).strip(),
                "zone": zone,
                "operator_id": None,
                "task_type": "receive",
                "duration_sec": None,
                "sku": sku,
                "extra": {
                    "provenance": "synthetic",
                    "synthesis_rule": "asn_receipt",
                    "source_fact": "asn",
                    "source_keys": {
                        "asn_line_id": a.get("asn_line_id"),
                        "po_id": a.get("po_id"),
                        "batch_id": a.get("batch_id"),
                    },
                    "qty_observed": qty,
                },
            }
        )

    for o in ol_rows:
        sku = o.get("sku")
        ship_ts = o.get("shipped_at_iso")
        ord_ts = o.get("ordered_at_iso")
        if ship_ts and str(ship_ts).strip():
            ts = str(ship_ts).strip()
            rule = "order_ship"
            ttype = "ship"
        elif ord_ts and str(ord_ts).strip():
            ts = str(ord_ts).strip()
            rule = "order_pick"
            ttype = "pick"
        else:
            continue
        out_rows.append(
            {
                "engagement_id": engagement_id,
                "batch_id": batch_id,
                "tenant_id": None,
                "warehouse_id": None,
                "completed_at": ts,
                "zone": "SHIP" if ttype == "ship" else "PICK",
                "operator_id": None,
                "task_type": ttype,
                "duration_sec": None,
                "sku": sku,
                "extra": {
                    "provenance": "synthetic",
                    "synthesis_rule": rule,
                    "source_fact": "order_line",
                    "source_keys": {
                        "order_external_id": o.get("order_external_id"),
                        "line_id": o.get("line_id"),
                        "batch_id": o.get("batch_id"),
                    },
                    "ship_to_postal": o.get("ship_to_postal"),
                    "channel": o.get("channel"),
                },
            }
        )

    if out_rows:
        await store.task_facts_insert(out_rows)

    return {
        "deleted": deleted,
        "inserted": len(out_rows),
        "synthetic_batch_id": batch_id if out_rows else None,
        "warning": None,
    }

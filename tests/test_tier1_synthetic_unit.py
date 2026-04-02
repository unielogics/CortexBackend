"""Tier-1 ingest + synthetic task generation (SQLite)."""

from __future__ import annotations

import asyncio
from pathlib import Path
import tempfile

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from unie_cortex.db import models as db_models
from unie_cortex.db.store import SqlCortexStore
from unie_cortex.services.synthetic_tasks import ensure_synthetic_tasks_from_tier1, rebuild_synthetic_tasks_from_tier1
from unie_cortex.spine.tier1_ingest import ingest_asn_csv, ingest_order_lines_csv


def _with_store(coro):
    async def _body():
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        path = tmp.name
        try:
            engine = create_async_engine(
                f"sqlite+aiosqlite:///{path}", echo=False, poolclass=NullPool
            )
            async with engine.begin() as conn:
                await conn.run_sync(db_models.Base.metadata.create_all)
            SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with SessionLocal() as session:
                st = SqlCortexStore(session)
                await st.engagement_create("e-tier1", "t", None, None)
                out = await coro(st)
                await session.commit()
            await engine.dispose()
            return out
        finally:
            Path(path).unlink(missing_ok=True)

    return asyncio.run(_body())


def test_ensure_synthetic_from_asn_and_order_lines():
    async def work(st: SqlCortexStore):
        await ingest_asn_csv(
            st,
            "e-tier1",
            b"AsnLineId,PoId,Sku,QtyExpected,QtyReceived,ExpectedAt,ReceivedAt\nL1,PO1,SKU1,10,10,2024-06-01,2024-06-02T14:00:00Z\n",
            "a.csv",
            {
                "AsnLineId": "asn_line_id",
                "PoId": "po_id",
                "Sku": "sku",
                "QtyExpected": "qty_expected",
                "QtyReceived": "qty_received",
                "ExpectedAt": "expected_at_iso",
                "ReceivedAt": "received_at_iso",
            },
        )
        await ingest_order_lines_csv(
            st,
            "e-tier1",
            b"OrderId,LineId,Sku,Qty,OrderedAt,ShippedAt\nO1,1,SKU2,2,2024-06-03,2024-06-04T16:00:00Z\n",
            "ol.csv",
            {
                "OrderId": "order_external_id",
                "LineId": "line_id",
                "Sku": "sku",
                "Qty": "quantity",
                "OrderedAt": "ordered_at_iso",
                "ShippedAt": "shipped_at_iso",
            },
        )
        r = await ensure_synthetic_tasks_from_tier1(st, "e-tier1")
        assert r["inserted"] == 2
        tasks = await st.task_facts_list(engagement_id="e-tier1")
        assert len(tasks) == 2
        syn = [t for t in tasks if (t.get("extra") or {}).get("provenance") == "synthetic"]
        assert len(syn) == 2
        types = {t.get("task_type") for t in syn}
        assert "receive" in types
        assert "ship" in types

        r2 = await ensure_synthetic_tasks_from_tier1(st, "e-tier1")
        assert r2["skipped"] is False
        assert r2["inserted"] == 2
        tasks3 = await st.task_facts_list(engagement_id="e-tier1")
        assert len(tasks3) == 2

    _with_store(work)


def test_rebuild_replaces_synthetic_only():
    async def work(st: SqlCortexStore):
        await ingest_order_lines_csv(
            st,
            "e-tier1",
            b"OrderId,LineId,Sku,Qty,OrderedAt,ShippedAt\nO9,9,SKU9,1,2024-07-01,\n",
            "ol.csv",
            {
                "OrderId": "order_external_id",
                "LineId": "line_id",
                "Sku": "sku",
                "Qty": "quantity",
                "OrderedAt": "ordered_at_iso",
                "ShippedAt": "shipped_at_iso",
            },
        )
        await st.task_facts_insert(
            [
                {
                    "engagement_id": "e-tier1",
                    "batch_id": "upload-batch",
                    "tenant_id": None,
                    "warehouse_id": None,
                    "completed_at": "2024-07-02T10:00:00Z",
                    "zone": "A",
                    "operator_id": "op1",
                    "task_type": "pick",
                    "duration_sec": 60.0,
                    "sku": "SKU9",
                    "extra": None,
                }
            ]
        )
        await ensure_synthetic_tasks_from_tier1(st, "e-tier1")
        tasks = await st.task_facts_list(engagement_id="e-tier1")
        assert len(tasks) == 1

        await rebuild_synthetic_tasks_from_tier1(st, "e-tier1")
        tasks2 = await st.task_facts_list(engagement_id="e-tier1")
        assert len(tasks2) == 2
        uploaded = [t for t in tasks2 if t.get("batch_id") == "upload-batch"]
        assert len(uploaded) == 1

    _with_store(work)

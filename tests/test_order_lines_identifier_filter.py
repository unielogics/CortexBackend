"""Order lines CSV ingest: optional ASIN/UPC row filters (Product Research upload)."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from unie_cortex.db import models as db_models
from unie_cortex.db.store import SqlCortexStore
from unie_cortex.spine.tier1_ingest import ingest_order_lines_csv
from unie_cortex.utils.identifiers import (
    normalize_asin_filter_param,
    normalize_upc_filter_param,
)


_OL_MAP = {
    "OrderId": "order_external_id",
    "LineId": "line_id",
    "Sku": "sku",
    "Qty": "quantity",
    "OrderedAt": "ordered_at_iso",
    "ShippedAt": "shipped_at_iso",
    "DestZip": "ship_to_postal",
    "Channel": "channel",
}


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
                await st.engagement_create("e-olfilter", "t", None, None)
                out = await coro(st)
                await session.commit()
            await engine.dispose()
            return out
        finally:
            Path(path).unlink(missing_ok=True)

    return asyncio.run(_body())


def test_ingest_order_lines_no_filter_stats_none():
    async def work(st: SqlCortexStore):
        csv = (
            "OrderId,LineId,Sku,Qty,OrderedAt,ShippedAt\n"
            "O1,1,KEEP,1,2024-06-03,2024-06-04T16:00:00Z\n"
            "O2,2,OTHER,1,2024-06-03,2024-06-04T16:00:00Z\n"
        )
        bid, n, stats = await ingest_order_lines_csv(
            st, "e-olfilter", csv.encode("utf-8"), "ol.csv", _OL_MAP
        )
        assert stats is None
        assert n == 2
        rows = await st.order_line_facts_list("e-olfilter")
        assert len(rows) == 2
        skus = {r.get("sku") for r in rows}
        assert skus == {"KEEP", "OTHER"}
        assert bid

    _with_store(work)


def test_ingest_order_lines_filter_asin_mapped_sku():
    async def work(st: SqlCortexStore):
        csv = (
            "OrderId,LineId,Sku,Qty,OrderedAt,ShippedAt\n"
            "O1,1,B0ABCDEFGH,1,2024-06-03,2024-06-04T16:00:00Z\n"
            "O2,2,B0ZZZZZZZZ,1,2024-06-03,2024-06-04T16:00:00Z\n"
        )
        fa = normalize_asin_filter_param("B0ABCDEFGH")
        bid, n, stats = await ingest_order_lines_csv(
            st,
            "e-olfilter",
            csv.encode("utf-8"),
            "ol.csv",
            _OL_MAP,
            filter_asin=fa,
            filter_upc=None,
        )
        assert stats is not None
        assert stats["rows_read"] == 2
        assert stats["rows_skipped_identifier"] == 1
        assert n == 1
        rows = await st.order_line_facts_list("e-olfilter")
        assert len(rows) == 1
        assert rows[0].get("sku") == "B0ABCDEFGH"
        assert bid

    _with_store(work)


def test_ingest_order_lines_filter_asin_unmapped_column():
    """ASIN appears only in a column not wired into canonical mapping — raw scan must match."""
    async def work(st: SqlCortexStore):
        csv = (
            "OrderId,LineId,Sku,AmazonAsin,Qty,OrderedAt,ShippedAt\n"
            "O1,1,MSKU-A,B0ABCDEFGH,1,2024-06-03,2024-06-04T16:00:00Z\n"
            "O2,2,MSKU-B,B0ZZZZZZZZ,1,2024-06-03,2024-06-04T16:00:00Z\n"
        )
        fa = normalize_asin_filter_param("b0abcdefgh")
        bid, n, stats = await ingest_order_lines_csv(
            st,
            "e-olfilter",
            csv.encode("utf-8"),
            "ol.csv",
            _OL_MAP,
            filter_asin=fa,
            filter_upc=None,
        )
        assert n == 1
        assert stats["rows_skipped_identifier"] == 1
        rows = await st.order_line_facts_list("e-olfilter")
        assert len(rows) == 1
        assert rows[0].get("sku") == "MSKU-A"
        assert bid

    _with_store(work)


def test_ingest_order_lines_filter_upc():
    async def work(st: SqlCortexStore):
        csv = (
            "OrderId,LineId,Sku,Qty,OrderedAt,ShippedAt\n"
            "O1,1,123456789012,1,2024-06-03,2024-06-04T16:00:00Z\n"
            "O2,2,999999999999,1,2024-06-03,2024-06-04T16:00:00Z\n"
        )
        fu = normalize_upc_filter_param("123456789012")
        _, n, stats = await ingest_order_lines_csv(
            st,
            "e-olfilter",
            csv.encode("utf-8"),
            "ol.csv",
            _OL_MAP,
            filter_asin=None,
            filter_upc=fu,
        )
        assert n == 1
        assert stats["rows_read"] == 2
        rows = await st.order_line_facts_list("e-olfilter")
        assert len(rows) == 1
        assert rows[0].get("sku") == "123456789012"

    _with_store(work)


def test_normalize_asin_filter_param_invalid():
    with pytest.raises(ValueError, match="ASIN"):
        normalize_asin_filter_param("short")


def test_normalize_upc_filter_param_invalid():
    with pytest.raises(ValueError, match="filter_upc"):
        normalize_upc_filter_param("12345")

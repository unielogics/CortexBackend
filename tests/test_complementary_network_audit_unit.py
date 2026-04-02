"""Complementary network audit service (async + SQLite)."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from unie_cortex.db import models as db_models
from unie_cortex.db.store import SqlCortexStore
from unie_cortex.network.demand_rollup import merge_label_and_order_line_demand_rollups, rollup_label_demand, rollup_order_lines_demand
from unie_cortex.services.complementary_network_audit import build_complementary_network_audit


class _FakeRSS:
    """Distance-shaped quotes: farther mock origin–dest ZIP3 gap → higher USD."""

    async def quote_shipment_detail(self, **kwargs):
        o = "".join(c for c in str(kwargs.get("origin_postal") or "") if c.isdigit())[:5].zfill(5)
        d = "".join(c for c in str(kwargs.get("dest_postal") or "") if c.isdigit())[:5].zfill(5)
        o3 = int(o[:3]) if len(o) >= 3 else 0
        d3 = int(d[:3]) if len(d) >= 3 else 0
        dist = abs(o3 - d3)
        return {"primary_usd": 5.0 + dist * 0.05, "rates": [], "source": "fake_rss"}


def test_merge_label_and_order_line_demand_rollups():
    labels = [{"dest_postal": "90001", "label_amount_usd": 1.0}] * 3
    ol = [{"ship_to_postal": "90001", "quantity": 1}] * 2
    lr = rollup_label_demand(labels)
    oroll = rollup_order_lines_demand(ol)
    m = merge_label_and_order_line_demand_rollups(lr, oroll)
    assert m["status"] == "complete"
    assert m["total_merged_lines"] == 5
    assert "900" in (m.get("tiers") or {}).get("hot_zip3", [])


def test_complementary_network_audit_complete_shape():
    asyncio.run(_complementary_audit_once())


async def _complementary_audit_once() -> None:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    path = tmp.name
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}", echo=False, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(db_models.Base.metadata.create_all)
        SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with SessionLocal() as session:
            store = SqlCortexStore(session)
            labels = [
                {"dest_postal": "072081234", "origin_postal": "07208", "label_amount_usd": 1.0},
                {"dest_postal": "90001", "origin_postal": "07208", "label_amount_usd": 1.0},
                {"dest_postal": "30303", "origin_postal": "07208", "label_amount_usd": 1.0},
            ]
            ol = [{"ship_to_postal": "98101", "quantity": 2}]
            nc = {"candidate_warehouses": [{"id": "p1", "postal": "07208", "label": "NJ"}]}
            out = await build_complementary_network_audit(
                store=store,
                tenant_id="pytest-tenant",
                labels=labels,
                order_lines=ol,
                network_context=nc,
                rss=_FakeRSS(),
                use_cache=False,
            )
            assert out["status"] == "complete"
            assert out["schema_version"] == "complementary_network_audit_v1"
            assert out["primary_origin_postal"] == "07208"
            assert out["tiered_total_nodes"] == 2
            assert len(out.get("selected_complement_nodes") or []) == 1
            assert out.get("lanes_sampled", 0) >= 1
            assert isinstance(out.get("per_destination_top"), list)
    finally:
        await engine.dispose()
        Path(path).unlink(missing_ok=True)

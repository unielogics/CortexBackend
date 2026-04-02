"""Operational fact queries must not return assessment (engagement-scoped) rows."""

from __future__ import annotations

import asyncio
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from unie_cortex.db import models
from unie_cortex.db.store import SqlCortexStore


async def _label_isolation(tmp_path: Path) -> None:
    dbf = tmp_path / "iso.db"
    url = f"sqlite+aiosqlite:///{dbf}"
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as s:
        st = SqlCortexStore(s)
        await st.label_facts_insert(
            [
                {
                    "engagement_id": None,
                    "tenant_id": "t_iso",
                    "warehouse_id": "w_iso",
                    "batch_id": None,
                    "tracking_number": "op1",
                    "carrier": "UPS",
                    "service_code": None,
                    "label_amount_usd": 9.0,
                    "weight_lb": 1.0,
                    "origin_postal": None,
                    "dest_postal": "10001",
                    "ship_date": None,
                    "sku": None,
                    "qty": None,
                    "line_amount_usd": None,
                },
                {
                    "engagement_id": "00000000-0000-0000-0000-00000000aa01",
                    "tenant_id": None,
                    "warehouse_id": None,
                    "batch_id": "b1",
                    "tracking_number": "au1",
                    "carrier": "FedEx",
                    "service_code": None,
                    "label_amount_usd": 3.0,
                    "weight_lb": 1.0,
                    "origin_postal": None,
                    "dest_postal": "90210",
                    "ship_date": None,
                    "sku": None,
                    "qty": None,
                    "line_amount_usd": None,
                },
            ]
        )
        await s.commit()
        rows = await st.label_facts_list(tenant_id="t_iso", warehouse_id="w_iso")
        assert len(rows) == 1
        assert rows[0]["tracking_number"] == "op1"
    await engine.dispose()


def test_label_facts_list_operational_excludes_engagement_rows(tmp_path):
    asyncio.run(_label_isolation(tmp_path))


async def _of_iso(tmp_path: Path) -> None:
    dbf = tmp_path / "iso2.db"
    url = f"sqlite+aiosqlite:///{dbf}"
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as s:
        st = SqlCortexStore(s)
        await st.order_financial_facts_insert(
            [
                {
                    "engagement_id": None,
                    "batch_id": None,
                    "tenant_id": "t2",
                    "warehouse_id": "w2",
                    "order_external_id": "O1",
                    "order_date_iso": "2024-01-01",
                    "email": None,
                    "asin": None,
                    "sku": None,
                    "line_title": None,
                    "revenue_usd": 10.0,
                    "marketplace_fees_usd": None,
                    "product_cogs_usd": None,
                    "prep_cost_usd": None,
                    "inbound_cost_usd": None,
                    "total_fees_usd": None,
                    "profit_usd": None,
                    "quantity": None,
                    "other_expenses_usd": None,
                    "ship_to_city": None,
                    "ship_to_state": None,
                    "ship_to_postal": None,
                    "ship_to_country": None,
                    "marketplace_fees_2026_csv_usd": None,
                    "total_fees_2026_csv_usd": None,
                    "profit_2026_csv_usd": None,
                    "marketplace_fees_2026_synthetic_usd": None,
                    "total_fees_2026_synthetic_usd": None,
                    "profit_2026_synthetic_usd": None,
                    "inflation_source": None,
                    "assumptions_version": None,
                    "inflation_components": None,
                    "referral_fees_modeled_usd": None,
                    "referral_fee_bucket": None,
                    "referral_fee_source": None,
                    "extra": None,
                },
                {
                    "engagement_id": "00000000-0000-0000-0000-00000000aa02",
                    "batch_id": "x",
                    "tenant_id": None,
                    "warehouse_id": None,
                    "order_external_id": "O2",
                    "order_date_iso": "2024-02-01",
                    "email": None,
                    "asin": None,
                    "sku": None,
                    "line_title": None,
                    "revenue_usd": 99.0,
                    "marketplace_fees_usd": None,
                    "product_cogs_usd": None,
                    "prep_cost_usd": None,
                    "inbound_cost_usd": None,
                    "total_fees_usd": None,
                    "profit_usd": None,
                    "quantity": None,
                    "other_expenses_usd": None,
                    "ship_to_city": None,
                    "ship_to_state": None,
                    "ship_to_postal": None,
                    "ship_to_country": None,
                    "marketplace_fees_2026_csv_usd": None,
                    "total_fees_2026_csv_usd": None,
                    "profit_2026_csv_usd": None,
                    "marketplace_fees_2026_synthetic_usd": None,
                    "total_fees_2026_synthetic_usd": None,
                    "profit_2026_synthetic_usd": None,
                    "inflation_source": None,
                    "assumptions_version": None,
                    "inflation_components": None,
                    "referral_fees_modeled_usd": None,
                    "referral_fee_bucket": None,
                    "referral_fee_source": None,
                    "extra": None,
                },
            ]
        )
        await s.commit()
        rows = await st.order_financial_facts_list(tenant_id="t2", warehouse_id="w2")
        assert len(rows) == 1
        assert rows[0]["order_external_id"] == "O1"
    await engine.dispose()


def test_order_financial_facts_list_operational_excludes_engagement(tmp_path):
    asyncio.run(_of_iso(tmp_path))

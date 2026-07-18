"""Cortex recurring Keepa-refresh scheduler.

Sibling of macro_decisions_scheduler.py. Keeps the Keepa snapshot cache
(keepa_snapshots) + normalized demand (sku_demand_snapshots) fresh so OMS product
research, SKU detail, and placement decisions read recent market data instead of
lazily refreshing only on request.

Freshness model (end state):
  - Per-request TTL cache: KEEPA_TTL_DAYS (default 30) — a lookup within TTL is a cache hit.
  - PRO-run force: PRODUCT_RESEARCH_KEEPA_REFRESH_HOURS (default 48) — a product-research run
    force-refreshes catalog ASINs older than this.
  - THIS scheduled sweep: every KEEPA_REFRESH_INTERVAL_HOURS (default 60h ~= 2.5 days), for each
    enabled tenant, force-refresh each catalog ASIN whose snapshot is older than
    KEEPA_REFRESH_STALE_HOURS (default 60h). Token-budget capped per sweep.

Invoked by uniecortex-keepa-refresh.timer (oneshot). Single-flight by construction (systemd
oneshot won't overlap). Per-tenant / per-ASIN try/except so one failure never aborts the sweep.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone

from sqlalchemy import select

from unie_cortex.db.database import SessionLocal
from unie_cortex.db.models import TenantRefreshSchedule
from unie_cortex.db.store import SqlCortexStore
from unie_cortex.integrations.keepa import KeepaService

logger = logging.getLogger("uniecortex.keepa_refresh_scheduler")
logging.basicConfig(
    level=os.environ.get("KEEPA_REFRESH_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

# Hard cap on Keepa API calls per sweep so a large catalog can't exhaust the token budget.
MAX_REFRESH_PER_SWEEP = int(os.environ.get("KEEPA_REFRESH_MAX_PER_SWEEP", "200"))
STALE_HOURS = float(os.environ.get("KEEPA_REFRESH_STALE_HOURS", "60"))
PER_TENANT_LIMIT = int(os.environ.get("KEEPA_REFRESH_PER_TENANT_LIMIT", "500"))


def _asin_of(item: dict) -> str | None:
    asin = str(item.get("asin") or "").strip().upper()
    return asin or None


async def tick_once() -> dict[str, int]:
    if SessionLocal is None:
        logger.warning("keepa_refresh: SessionLocal is None; skipping")
        return {"tenants": 0, "refreshed": 0}

    refreshed = 0
    failed = 0
    tenants = 0
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(TenantRefreshSchedule).where(TenantRefreshSchedule.enabled.is_(True))
            )
        ).scalars().all()
        if not rows:
            logger.info("keepa_refresh: no enabled tenants")
            return {"tenants": 0, "refreshed": 0}

        store = SqlCortexStore(session)
        keepa = KeepaService(store=store)
        budget = MAX_REFRESH_PER_SWEEP

        for row in rows:
            tenant_id = row.tenant_id
            if not tenant_id:
                continue
            tenants += 1
            try:
                items = await store.sku_catalog_list(tenant_id, limit=PER_TENANT_LIMIT)
            except Exception as exc:  # noqa: BLE001
                logger.exception("keepa_refresh tenant=%s catalog list failed: %s", tenant_id, exc)
                continue
            # De-dupe ASINs across the tenant's catalog.
            asins = []
            seen = set()
            for it in items or []:
                a = _asin_of(it)
                if a and a not in seen:
                    seen.add(a)
                    asins.append(a)
            for asin in asins:
                if budget <= 0:
                    logger.warning("keepa_refresh: per-sweep budget (%d) exhausted; stopping", MAX_REFRESH_PER_SWEEP)
                    break
                try:
                    # force_refresh re-fetches + re-persists keepa_snapshots + sku_demand_snapshots.
                    await keepa.product(asin, domain=1, tenant_id=tenant_id, force_refresh=True)
                    refreshed += 1
                    budget -= 1
                except Exception as exc:  # noqa: BLE001
                    failed += 1
                    logger.warning("keepa_refresh tenant=%s asin=%s failed: %s", tenant_id, asin, str(exc)[:160])
            if budget <= 0:
                break

    logger.info("keepa_refresh swept %d tenant(s), refreshed %d ASIN(s), %d failed", tenants, refreshed, failed)
    return {"tenants": tenants, "refreshed": refreshed, "failed": failed}


async def main_loop() -> None:
    interval_hours = float(os.environ.get("KEEPA_REFRESH_INTERVAL_HOURS", "60"))
    while True:
        started = datetime.now(timezone.utc)
        try:
            await tick_once()
        except Exception:  # noqa: BLE001
            logger.exception("keepa_refresh tick failed")
        elapsed = (datetime.now(timezone.utc) - started).total_seconds()
        await asyncio.sleep(max(300.0, interval_hours * 3600 - elapsed))


if __name__ == "__main__":
    if os.environ.get("KEEPA_REFRESH_DAEMON") == "1":
        asyncio.run(main_loop())
    else:
        asyncio.run(tick_once())

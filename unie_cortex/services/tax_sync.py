"""Orchestrate nationwide tax snapshot sync (TaxJar summary_rates or mock)."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from unie_cortex.db.store import CortexStore
from unie_cortex.integrations.taxjar_rates import fetch_rates_for_sync


async def run_nationwide_tax_sync(store: CortexStore) -> dict[str, Any]:
    run_id = str(uuid4())
    await store.tax_sync_run_insert(run_id, "taxjar")
    try:
        rows, provider = await fetch_rates_for_sync()
        n = await store.tax_jurisdiction_replace_scope_provider("__system__", provider, rows)
        await store.tax_sync_run_finish(run_id, status="complete", regions_count=n)
        return {
            "status": "complete",
            "run_id": run_id,
            "provider": provider,
            "regions_written": n,
        }
    except Exception as e:
        await store.tax_sync_run_finish(
            run_id, status="error", regions_count=0, error_message=str(e)[:2000]
        )
        raise

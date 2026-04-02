"""Sales tax estimate from stored jurisdiction snapshots + tenant nexus."""

from __future__ import annotations

from typing import Any

from unie_cortex.db.store import CortexStore

_SCOPE = "__system__"
_PROVIDER = "taxjar"


async def estimate_sales_tax_usd(
    store: CortexStore,
    tenant_id: str,
    *,
    destination_state: str,
    taxable_subtotal_usd: float,
    country_code: str = "US",
) -> dict[str, Any]:
    """
    If tenant has nexus in destination_state, apply average_rate from last sync; else 0.
    Rates in DB are decimal (e.g. 0.0825).
    """
    st = (destination_state or "").strip().upper()[:8]
    sub = max(0.0, float(taxable_subtotal_usd))
    nexus = await store.tenant_sales_tax_nexus_list(tenant_id)
    has_nexus = st in set(nexus)
    snap = await store.tax_jurisdiction_get(_SCOPE, _PROVIDER, country_code, st)
    rate = None
    if snap:
        rate = snap.get("average_rate")
        if rate is None:
            rate = snap.get("minimum_rate")
    try:
        r = float(rate) if rate is not None else None
    except (TypeError, ValueError):
        r = None
    if not has_nexus:
        return {
            "destination_state": st,
            "taxable_subtotal_usd": round(sub, 2),
            "estimated_sales_tax_usd": 0.0,
            "effective_rate": None,
            "nexus_in_destination": False,
            "note": "No tenant nexus in destination; estimated tax 0 (modeling only).",
        }
    if r is None:
        return {
            "destination_state": st,
            "taxable_subtotal_usd": round(sub, 2),
            "estimated_sales_tax_usd": 0.0,
            "effective_rate": None,
            "nexus_in_destination": True,
            "note": "Nexus in destination but no tax snapshot for this state — run POST /v1/integrations/tax/sync.",
        }
    tax = round(sub * r, 2)
    return {
        "destination_state": st,
        "taxable_subtotal_usd": round(sub, 2),
        "estimated_sales_tax_usd": tax,
        "effective_rate": r,
        "nexus_in_destination": True,
        "tax_snapshot_refreshed_at": snap.get("refreshed_at") if snap else None,
        "note": None,
    }

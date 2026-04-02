"""Sales-tax reference rows for placement / PRO — nexus + __system__ rate table."""

from __future__ import annotations

from typing import Any

from unie_cortex.db.store import CortexStore


async def enrich_sales_tax_modeling_for_placement(
    store: CortexStore,
    tenant_id: str,
    demand_weighting: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    Attach destination-state rate preview (top states from demand_weighting.state_weights_preview)
    and a demand-share-weighted average rate across nexus destinations only.
    """
    dw = demand_weighting if isinstance(demand_weighting, dict) else {}
    preview_states = dw.get("state_weights_preview") or []
    states: list[str] = []
    share_by_state: dict[str, float] = {}
    for row in preview_states:
        if not isinstance(row, dict):
            continue
        st = str(row.get("state") or "").strip().upper()
        if len(st) != 2 or not st.isalpha():
            continue
        if st not in states:
            states.append(st)
        try:
            share_by_state[st] = float(row.get("share") or 0.0)
        except (TypeError, ValueError):
            share_by_state[st] = 0.0

    nexus_list = await store.tenant_sales_tax_nexus_list(tenant_id)
    nexus = {str(x).strip().upper() for x in nexus_list if str(x).strip()}

    rows: list[dict[str, Any]] = []
    for st in states[:20]:
        snap = await store.tax_jurisdiction_get("__system__", "taxjar", "US", st)
        avg = snap.get("average_rate") if snap else None
        try:
            avg_f = float(avg) if avg is not None else None
        except (TypeError, ValueError):
            avg_f = None
        rows.append(
            {
                "state": st,
                "tenant_has_nexus": st in nexus,
                "average_rate": avg_f,
                "minimum_rate": snap.get("minimum_rate") if snap else None,
                "has_rate_table": snap is not None,
                "refreshed_at": snap.get("refreshed_at") if snap else None,
            }
        )

    w_num = 0.0
    w_den = 0.0
    for st in states[:20]:
        sh = float(share_by_state.get(st, 0.0))
        if sh <= 0:
            continue
        if st not in nexus:
            continue
        r = next((x.get("average_rate") for x in rows if x.get("state") == st), None)
        if r is None:
            continue
        try:
            rf = float(r)
        except (TypeError, ValueError):
            continue
        w_num += sh * rf
        w_den += sh

    return {
        "destination_tax_rate_preview": rows,
        "weighted_average_sales_tax_rate_nexus_destinations": round(w_num / w_den, 6) if w_den > 1e-12 else None,
        "weighted_share_covering_nexus_preview_states": round(w_den, 6) if w_den > 1e-12 else None,
        "placement_tax_note": (
            "average_rate is from __system__ tax_jurisdiction_snapshots (TaxJar summary_rates or mock sync). "
            "Weighted average uses state_weights_preview shares only where tenant_has_nexus."
        ),
    }

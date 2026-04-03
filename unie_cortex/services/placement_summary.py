"""
Structured + human-readable inventory placement summary (machine + narrative).

Pairs with Keepa-derived velocity and optional warehouse network. Does not replace WMS;
feeds AI and dashboards.
"""

from __future__ import annotations

import math
from typing import Any


def build_inventory_placement_summary(
    *,
    asin: str | None,
    title: str | None,
    product_origin_postal: str | None,
    monthly_units_est_mid: float | None,
    target_days_cover: float | None = None,
    suggested_min_active_warehouses: int = 1,
    warehouse_nodes: list[dict[str, Any]] | None = None,
    product_origin_city: str | None = None,
    product_origin_region: str | None = None,
) -> dict[str, Any]:
    """
    ``warehouse_nodes``: optional ``[{ "warehouse_id": "NJ", "postal": "07001" }, ...]``.
    When empty, split uses generic placeholders (IDs supplied later from your network API).
    """
    if target_days_cover is None:
        from unie_cortex.config import settings

        target_days_cover = float(getattr(settings, "planning_default_target_days_cover", 75.0) or 75.0)
    wh = warehouse_nodes or []
    n_nodes = max(1, int(suggested_min_active_warehouses), len(wh) or 1)
    mid = float(monthly_units_est_mid or 0.0)
    daily = mid / 30.0 if mid > 0 else None
    cover_units: int | None = None
    if daily and daily > 0:
        cover_units = max(1, int(math.ceil(daily * float(target_days_cover))))

    splits: list[dict[str, Any]] = []
    if wh:
        use = wh[:n_nodes] if len(wh) >= n_nodes else wh
        if not use:
            use = [{"warehouse_id": f"node_{i + 1}", "postal": None} for i in range(n_nodes)]
        per = max(1, int(math.ceil((cover_units or 0) / max(len(use), 1)))) if cover_units else None
        for i, w in enumerate(use):
            wid = w.get("warehouse_id") or f"warehouse_{i + 1}"
            pc = w.get("postal")
            u = per if cover_units else None
            splits.append(
                {
                    "warehouse_id": wid,
                    "postal": pc,
                    "suggested_units_for_target_cover": u,
                    "target_days_cover": target_days_cover,
                    "note": f"~{target_days_cover:.0f}d cover at est. {daily:.2f} units/day (from monthly est.)."
                    if daily
                    else "Need velocity estimate to size units.",
                }
            )
    else:
        for i in range(n_nodes):
            wid = f"warehouse_slot_{i + 1}"
            share = 1.0 / n_nodes
            u = int(math.ceil((cover_units or 0) * share)) if cover_units else None
            splits.append(
                {
                    "warehouse_id": wid,
                    "postal": None,
                    "suggested_units_for_target_cover": u,
                    "target_days_cover": target_days_cover,
                    "allocation_share_of_cover_est": round(share, 4),
                }
            )

    loc_bits = []
    if product_origin_city:
        loc_bits.append(str(product_origin_city).strip())
    if product_origin_region:
        loc_bits.append(str(product_origin_region).strip().upper())
    loc_suffix = f" ({', '.join(loc_bits)})" if loc_bits else ""
    origin_line = (
        f"Product origin (bulk / supplier): ZIP {product_origin_postal}{loc_suffix}."
        if product_origin_postal
        else "Product origin ZIP not set — add product_origin_postal on scenario/catalog for first-touch routing."
    )
    if not product_origin_postal and loc_bits:
        origin_line = (
            "Product origin ZIP not set — add product_origin_postal for routing; "
            f"city/state hint: {', '.join(loc_bits)}."
        )
    vel_line = (
        f"Seller-scoped planning velocity ~{mid:,.0f} units/month (~{daily:.2f}/day) — same basis as procurement and multi-node hints."
        if mid > 0
        else "Velocity unknown — size placement from your label history or ASIN demand when available."
    )
    cover_line = (
        f"For ~{target_days_cover:.0f} days cover, plan ~{cover_units} units in the active network (rough cut)."
        if cover_units
        else "Cannot compute cover quantity without monthly velocity mid."
    )
    split_line = (
        f"Split across {len(splits)} active location(s) below; tune with hot-ZIP demand and rate-shop grid."
        if splits
        else "Define warehouses in the request to name-specific DC splits."
    )

    out: dict[str, Any] = {
        "assumptions_version": "inventory_placement_summary_v1",
        "asin": asin,
        "title": title,
        "product_origin_postal": product_origin_postal,
        "target_days_cover": target_days_cover,
        "monthly_units_est_mid_used": mid if mid > 0 else None,
        "est_daily_units_from_monthly": round(daily, 4) if daily else None,
        "suggested_total_units_for_target_cover": cover_units,
        "suggested_min_active_warehouses": n_nodes,
        "warehouse_splits": splits,
        "narrative_bullets": [origin_line, vel_line, cover_line, split_line],
        "machine": {
            "fields_for_downstream": [
                "product_origin_postal",
                "product_origin_city",
                "product_origin_region",
                "suggested_total_units_for_target_cover",
                "warehouse_splits[].warehouse_id",
                "warehouse_splits[].suggested_units_for_target_cover",
            ],
        },
    }
    if product_origin_city:
        out["product_origin_city"] = str(product_origin_city).strip()
    if product_origin_region:
        out["product_origin_region"] = str(product_origin_region).strip()
    return out

"""
Multi-warehouse placement hints for 3P sellers (conservative).

High velocity and/or crowded buy box → favor stock in **multiple** nodes for cheaper
last mile — without claiming Amazon buy box share for the seller.
"""

from __future__ import annotations

from typing import Any


def build_placement_hints(
    *,
    monthly_units_est_mid: float | None,
    buybox_context: dict[str, Any] | None,
    high_velocity_threshold: float = 4000.0,
) -> dict[str, Any]:
    bb = buybox_context or {}
    mid = float(monthly_units_est_mid or 0.0)
    comp = (bb.get("competition_level") or "unknown").lower()
    dominance = (bb.get("dominance_hint") or "unknown").lower()

    # Minimum nodes to consider for inbound + regional last mile
    min_active_warehouses = 1
    reasons: list[str] = []

    if mid >= high_velocity_threshold:
        min_active_warehouses = max(min_active_warehouses, 2)
        reasons.append(
            f"Estimated marketplace velocity (~{mid:,.0f} units/mo) supports multi-node stock for last-mile savings."
        )

    if comp in ("high", "medium"):
        min_active_warehouses = max(min_active_warehouses, 2)
        reasons.append(
            "Elevated seller/offer competition on the listing — diversify geography to protect service levels."
        )

    third_party_cautions = [
        "You are typically **not** the brand owner — do not treat Keepa marketplace signals as **your** buy box share.",
        "Use placement hints as **inventory / logistics** guidance; pricing and listing tactics need separate tools.",
    ]
    if dominance == "amazon_or_retail_strong":
        third_party_cautions.append(
            "Amazon or major retail may dominate the buy box — aggressive multi-DC placement still helps **your** fulfilled orders, not Amazon's share."
        )

    return {
        "suggested_min_active_warehouses": min_active_warehouses,
        "reasons": reasons,
        "third_party_seller_cautions": third_party_cautions,
        "parameters": {
            "high_velocity_threshold": high_velocity_threshold,
            "competition_level_used": comp,
            "dominance_hint_used": dominance,
        },
    }

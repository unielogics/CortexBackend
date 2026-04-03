"""FTL linehaul mock — cheaper per lb at high volume than LTL for same lane."""

from __future__ import annotations

import math


def mock_ftl_quote_usd(
    *,
    total_weight_lb: float,
    total_cube_cuft: float,
    pallet_positions_est: float = 1.0,
    min_charge_usd: float = 1800.0,
    base_usd: float = 950.0,
    per_lb_usd: float = 0.012,
    per_pallet_usd: float = 35.0,
    cube_step_cuft: float = 300.0,
    per_cube_step_usd: float = 85.0,
) -> dict:
    """
    Full-truck style charge: high minimum, low marginal $/lb vs LTL.
    ``cube_step`` approximates partial trailer use above a floor.
    """
    w = max(0.0, float(total_weight_lb))
    cube = max(0.0, float(total_cube_cuft))
    pallets = max(1.0, float(pallet_positions_est))

    cube_tiers = math.ceil(cube / cube_step_cuft) if cube > 0 else 1
    subtotal = base_usd + w * per_lb_usd + pallets * per_pallet_usd + cube_tiers * per_cube_step_usd
    total = max(min_charge_usd, subtotal)

    return {
        "mode": "ftl",
        "total_usd": round(total, 2),
        "total_weight_lb": round(w, 2),
        "total_cube_cuft": round(cube, 3),
        "pallet_positions_est": round(pallets, 2),
        "components_usd": {
            "base": base_usd,
            "weight_line": round(w * per_lb_usd, 2),
            "pallet_line": round(pallets * per_pallet_usd, 2),
            "cube_tiers": cube_tiers,
            "cube_line": round(cube_tiers * per_cube_step_usd, 2),
            "min_applied": total == min_charge_usd and subtotal < min_charge_usd,
        },
        "source": "network_ftl_mock_v1",
        "display_carrier_name": "Unie mock FTL (deterministic — not carrier-rated)",
    }


def choose_linehaul_mode(
    total_weight_lb: float,
    *,
    freight_mode: str = "auto",
    ftl_threshold_total_lb: float = 12_000.0,
) -> str:
    """Returns ``ltl`` or ``ftl``."""
    fm = (freight_mode or "auto").lower().strip()
    if fm == "ltl":
        return "ltl"
    if fm == "ftl":
        return "ftl"
    return "ftl" if total_weight_lb >= ftl_threshold_total_lb else "ltl"

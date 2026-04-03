"""Pallet-aware LTL mock: unit cube vs reference pallet (48×40×70), space + weight → USD."""

from __future__ import annotations

import math

from unie_cortex.network.pallet_defaults import (
    REFERENCE_PALLET_HEIGHT_IN,
    REFERENCE_PALLET_LENGTH_IN,
    REFERENCE_PALLET_WIDTH_IN,
    max_units_on_reference_pallet,
    reference_pallet_cuft,
)


def sku_cube_cuft(length_in: float, width_in: float, height_in: float, qty: int) -> float:
    per = float(length_in) * float(width_in) * float(height_in) / 1728.0
    return max(0.0, per * max(0, int(qty)))


def mock_ltl_quote_usd(
    *,
    weight_lb: float,
    length_in: float,
    width_in: float,
    height_in: float,
    qty: int,
    pallet_max_cuft: float | None = None,
    min_charge_usd: float = 125.0,
    per_lb_usd: float = 0.06,
    per_pallet_slot_usd: float = 48.0,
) -> dict:
    """
    ``pallet_max_cuft`` defaults to **48×40×70** reference slot (not a full 53' trailer).

    Returns **per-unit** linehaul allocation for this mock move at ``qty`` (split cost across
    units — not “you moved a full pallet of one SKU” unless cube fills the slot).
    """
    slot = float(pallet_max_cuft) if pallet_max_cuft is not None else reference_pallet_cuft()
    total_w = max(0.0, float(weight_lb) * max(0, int(qty)))
    cube = sku_cube_cuft(length_in, width_in, height_in, qty)
    unit_cube = sku_cube_cuft(length_in, width_in, height_in, 1)
    pallet_positions = max(1.0, math.ceil(cube / slot)) if cube > 0 else 1.0
    if cube <= 0:
        pallet_positions = max(1.0, total_w / 2000.0)

    weight_line = total_w * per_lb_usd
    space_line = pallet_positions * per_pallet_slot_usd
    subtotal = max(min_charge_usd, weight_line + space_line)

    share_of_one_pallet_by_cube = min(1.0, unit_cube / slot) if unit_cube > 0 and slot > 0 else 0.0
    share_of_reference_pallet_for_qty = min(1.0, cube / slot) if cube > 0 and slot > 0 else 0.0

    q = max(1, int(qty))
    usd_per_unit_linehaul = round(subtotal / q, 6)

    return {
        "total_usd": round(subtotal, 2),
        "total_weight_lb": round(total_w, 2),
        "total_cube_cuft": round(cube, 4),
        "unit_cube_cuft": round(unit_cube, 6),
        "reference_pallet_dims_in": {
            "length": REFERENCE_PALLET_LENGTH_IN,
            "width": REFERENCE_PALLET_WIDTH_IN,
            "height": REFERENCE_PALLET_HEIGHT_IN,
        },
        "reference_pallet_cuft": round(slot, 4),
        "max_units_fit_reference_pallet_floor_est": max_units_on_reference_pallet(length_in, width_in, height_in),
        "pallet_positions_est": round(pallet_positions, 2),
        "fraction_of_one_pallet_slot_by_unit_cube": round(share_of_one_pallet_by_cube, 6),
        "fraction_of_one_pallet_slot_by_qty_cube": round(share_of_reference_pallet_for_qty, 6),
        "at_qty": q,
        "linehaul_usd_per_unit_at_this_qty": usd_per_unit_linehaul,
        "multi_tenant_note": (
            "Linehaul $ is divided by ``at_qty`` for **this SKU’s share**; pooled pallets split by weight/cube in /allocation/linehaul-split."
        ),
        "components_usd": {
            "weight_line": round(weight_line, 2),
            "pallet_space_line": round(space_line, 2),
            "min_applied": subtotal == min_charge_usd and (weight_line + space_line) < min_charge_usd,
        },
        "source": "network_ltl_mock_v2",
        "display_carrier_name": "Unie mock LTL (deterministic — not carrier-rated)",
    }

"""
Seller / order-planning consolidated linehaul: charge analyzed cohort as a cube fraction
of one reference mixed pallet (LTL or FTL baseline × fraction). Not used by TMS.
"""

from __future__ import annotations

from typing import Any, Literal

from unie_cortex.network.ftl_mock import mock_ftl_quote_usd
from unie_cortex.network.ltl_mock import mock_ltl_quote_usd
from unie_cortex.network.pallet_defaults import (
    REFERENCE_PALLET_HEIGHT_IN,
    REFERENCE_PALLET_LENGTH_IN,
    REFERENCE_PALLET_WIDTH_IN,
    reference_pallet_cuft,
)
from unie_cortex.network.scenarios_core import scale_consolidated_linehaul_leg

LinehaulMode = Literal["ltl", "ftl"]

_NOMINAL_WEIGHT_MIN_LB = 500.0
_NOMINAL_WEIGHT_MAX_LB = 2500.0


def pallet_slot_fraction(*, total_cuft: float, slot_cuft: float | None = None) -> float:
    slot = float(slot_cuft) if slot_cuft is not None else reference_pallet_cuft()
    if slot <= 0:
        return 1.0
    return min(1.0, max(0.0, float(total_cuft) / slot))


def nominal_mixed_pallet_weight_lb(
    total_w: float,
    fraction: float,
    *,
    lo: float = _NOMINAL_WEIGHT_MIN_LB,
    hi: float = _NOMINAL_WEIGHT_MAX_LB,
) -> float:
    """Implied density on a full slot: total_w / fraction, clamped for stable mock tariffs."""
    f = max(float(fraction), 1e-6)
    implied = float(total_w) / f
    return min(hi, max(lo, implied))


def build_seller_consolidated_linehaul_leg(
    *,
    mode: LinehaulMode,
    qty: int,
    total_w: float,
    total_cuft: float,
    consolidated_linehaul_cost_multiplier: float,
) -> dict[str, Any]:
    slot = reference_pallet_cuft()
    fraction = pallet_slot_fraction(total_cuft=total_cuft, slot_cuft=slot)
    nominal_w = nominal_mixed_pallet_weight_lb(total_w, fraction)

    if mode == "ltl":
        baseline = mock_ltl_quote_usd(
            weight_lb=nominal_w,
            length_in=REFERENCE_PALLET_LENGTH_IN,
            width_in=REFERENCE_PALLET_WIDTH_IN,
            height_in=REFERENCE_PALLET_HEIGHT_IN,
            qty=1,
        )
        base_total = float(baseline["total_usd"])
        display_carrier = str(baseline.get("display_carrier_name") or "")
    else:
        baseline = mock_ftl_quote_usd(
            total_weight_lb=nominal_w,
            total_cube_cuft=max(slot, 1.0),
            pallet_positions_est=1.0,
        )
        base_total = float(baseline["total_usd"])
        display_carrier = str(baseline.get("display_carrier_name") or "")

    scaled_total = round(fraction * base_total, 2)
    q = max(1, int(qty))

    out: dict[str, Any] = {
        "mode": mode,
        "total_usd": scaled_total,
        "total_weight_lb": round(float(total_w), 2),
        "total_cube_cuft": round(float(total_cuft), 4),
        "at_qty": q,
        "linehaul_usd_per_unit_at_this_qty": round(scaled_total / q, 6),
        "seller_mixed_pallet_basis_v1": True,
        "reference_pallet_cuft": round(slot, 4),
        "analyzed_total_cuft": round(float(total_cuft), 4),
        "pallet_slot_fraction": round(fraction, 6),
        "baseline_full_reference_pallet_usd": round(base_total, 2),
        "nominal_mixed_pallet_weight_lb_for_baseline": round(nominal_w, 2),
        "nominal_weight_clamp_lb": {"min": _NOMINAL_WEIGHT_MIN_LB, "max": _NOMINAL_WEIGHT_MAX_LB},
        "linehaul_pricing_model_note": (
            "Seller optimization: total_usd = pallet_slot_fraction × mock linehaul for one reference "
            f"48×40×70 slot ({mode.upper()} baseline); cohort cube / reference_pallet_cuft."
        ),
        "source": "network_seller_mixed_pallet_linehaul_v1",
        "display_carrier_name": display_carrier or "Unie mock linehaul (seller mixed-pallet basis)",
        "components_usd": {
            "scaled_from_baseline_total_usd": round(base_total, 2),
            "pallet_slot_fraction_applied": round(fraction, 6),
            "baseline_components_usd": baseline.get("components_usd"),
        },
    }
    if mode == "ltl":
        out["reference_pallet_dims_in"] = baseline.get("reference_pallet_dims_in")

    return scale_consolidated_linehaul_leg(out, consolidated_linehaul_cost_multiplier)

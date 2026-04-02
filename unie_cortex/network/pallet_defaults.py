"""Reference pallet for LTL / cube math (industry-common 48×40, 70\" max stack height)."""

from __future__ import annotations

# Default “slot” used for cube vs pallet comparisons (not a carrier tariff).
REFERENCE_PALLET_LENGTH_IN = 48.0
REFERENCE_PALLET_WIDTH_IN = 40.0
REFERENCE_PALLET_HEIGHT_IN = 70.0


def reference_pallet_cuft() -> float:
    return (
        REFERENCE_PALLET_LENGTH_IN
        * REFERENCE_PALLET_WIDTH_IN
        * REFERENCE_PALLET_HEIGHT_IN
        / 1728.0
    )


def max_units_on_reference_pallet(unit_length_in: float, unit_width_in: float, unit_height_in: float) -> int:
    """Floor of how many units fit if each uses full rectangular cube (naive upper bound)."""
    import math

    try:
        u = float(unit_length_in) * float(unit_width_in) * float(unit_height_in) / 1728.0
    except (TypeError, ValueError):
        return 0
    if u <= 0:
        return 0
    return max(1, int(math.floor(reference_pallet_cuft() / u)))

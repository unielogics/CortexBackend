"""Case-pack (box-integrity) transfer sizing.

Business rule (locked): Cortex must NEVER suggest breaking a case. If a product
ships in boxes of 100 and the "ideal" rebalance quantity is 75, the engine must
snap that to a whole number of boxes rather than emit 75.

Rounding policy = **nearest full box, capped**:
  - Round the ideal quantity to the NEAREST whole case-pack multiple
    (75 -> 100, 130 -> 100, 160 -> 200).
  - Never exceed the whole boxes actually available at the source
    (cap by ``whole_boxes_available``).
  - Never emit a positive transfer smaller than 1 full box: if the ideal is at
    least one case, ship at least one case (subject to the source cap); if the
    ideal is below half a case AND rounding-to-nearest would drop it to 0, it is
    held (0) — we do not ship a whole case to satisfy a sub-half-case need.

When case-pack data is missing or <= 1, the quantity passes through unchanged
(no snapping) so the engine degrades gracefully until per-SKU pack size flows in
from the WMS snapshot feed.

This mirrors the multiple-rounding already used in ``api/oms.py`` (carton math)
and ``network/inventory_doh.py`` (reorder pack rounding), consolidated here so
the transfer engine and the replenishment planner share one implementation.
"""
from __future__ import annotations

from typing import Any


def snap_to_case_pack(
    ideal_units: float,
    units_per_case: float | int | None,
    whole_boxes_available: float | int | None = None,
) -> int:
    """Snap an ideal transfer quantity to a whole number of case-pack units.

    Args:
        ideal_units: the unconstrained ideal quantity the heuristic wants to move.
        units_per_case: sellable units in one full case/box. None/<=1 -> passthrough.
        whole_boxes_available: cap in WHOLE BOXES available at the source. None ->
            uncapped (caller has already bounded ``ideal_units`` by on-hand).

    Returns:
        A whole-case-multiple integer quantity (>= 0). Never breaks a case.
    """
    try:
        ideal = float(ideal_units)
    except (TypeError, ValueError):
        return 0
    if ideal <= 0:
        return 0

    # No/degenerate pack size -> passthrough (round to whole units, floor to on-hand).
    upc = _coerce_positive_int(units_per_case)
    if upc is None or upc <= 1:
        units = int(ideal)
        if whole_boxes_available is not None:
            # With upc<=1 "boxes" == units; treat the cap as a unit cap.
            cap = _coerce_nonneg_int(whole_boxes_available)
            if cap is not None:
                units = min(units, cap)
        return max(0, units)

    # Nearest whole number of boxes.
    boxes = int(_round_half_up(ideal / upc))

    # Never ship a positive transfer smaller than 1 box when the need is >= 1 case.
    if boxes < 1 and ideal >= upc:
        boxes = 1

    # Cap by whole boxes physically available at the source.
    if whole_boxes_available is not None:
        cap_boxes = _coerce_nonneg_int(whole_boxes_available)
        if cap_boxes is not None:
            boxes = min(boxes, cap_boxes)

    return max(0, boxes) * upc


def annotate_leg_with_case_pack(
    leg: dict[str, Any],
    ideal_units: float,
    units_per_case: float | int | None,
    snapped_units: int,
) -> dict[str, Any]:
    """Attach box-integrity metadata to a transfer_set leg for the before/after UI.

    Adds ``ideal_units`` (pre-snap), ``units_per_case``, and ``boxes`` so the
    Cortex review table can render "75 -> 100 (1 full case)".
    """
    upc = _coerce_positive_int(units_per_case)
    leg["ideal_units"] = int(round(float(ideal_units))) if ideal_units is not None else None
    leg["units_per_case"] = upc
    leg["boxes"] = int(snapped_units // upc) if (upc and upc > 0) else None
    return leg


def _round_half_up(x: float) -> int:
    """Round to nearest, halves up (Python's round() is banker's rounding)."""
    import math

    return int(math.floor(x + 0.5))


def _coerce_positive_int(v: Any) -> int | None:
    try:
        n = int(float(v))
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _coerce_nonneg_int(v: Any) -> int | None:
    try:
        n = int(float(v))
    except (TypeError, ValueError):
        return None
    return n if n >= 0 else None

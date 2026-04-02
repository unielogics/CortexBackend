"""Mock fleet (tractors + trailer capacity signals) for draft / approval intelligence.

``mock_available_*`` simulates space TMS has not committed on each unit (not ELD truth).
"""

from __future__ import annotations

from typing import Any


def list_mock_tractors() -> list[dict[str, Any]]:
    """
    20 tractors with mixed situations for tuning draft proposals and UI.

    Fields are stable for API consumers; values are deterministic mocks.
    """
    return [
        _row("TRK-001", "DRY_VAN", "08817", "NJ", 48000, 3400, 26, 42000, 3000, 22, "high_availability"),
        _row("TRK-002", "DRY_VAN", "07094", "NJ", 48000, 3400, 26, 8000, 900, 5, "near_capacity_committed"),
        _row("TRK-003", "DRY_VAN", "19103", "PA", 48000, 3400, 26, 38000, 2700, 20, "moderate_slack"),
        _row("TRK-004", "REEFER", "30349", "GA", 47000, 3200, 26, 45000, 3100, 24, "reefer_mostly_empty"),
        _row("TRK-005", "REEFER", "33126", "FL", 47000, 3200, 26, 12000, 800, 4, "reefer_tight"),
        _row("TRK-006", "DRY_VAN", "75208", "TX", 48000, 3400, 26, 35000, 2500, 18, "yard_hold_partial"),
        _row("TRK-007", "FLATBED", "90011", "CA", 48000, 3400, 26, 46000, 3300, 25, "flatbed_open_deck"),
        _row("TRK-008", "DRY_VAN", "98134", "WA", 48000, 3400, 26, 2000, 200, 1, "almost_full"),
        _row("TRK-009", "DRY_VAN", "48211", "MI", 48000, 3400, 26, 40000, 2900, 23, "balanced_slack"),
        _row("TRK-010", "DRY_VAN", "08817", "NJ", 48000, 3400, 26, 47500, 3350, 25, "minimal_slack_same_yard"),
        _row("TRK-011", "DRY_VAN", "43217", "OH", 48000, 3400, 26, 36000, 2600, 19, "domicile_oh_hub"),
        _row("TRK-012", "DRY_VAN", "60607", "IL", 48000, 3400, 26, 44000, 3050, 21, "midwest_lane"),
        _row("TRK-013", "REEFER", "08817", "NJ", 47000, 3200, 26, 30000, 2100, 16, "reefer_moderate_nj"),
        _row("TRK-014", "DRY_VAN", "37209", "TN", 48000, 3400, 26, 15000, 1100, 7, "post_delivery_light"),
        _row("TRK-015", "DRY_VAN", "33607", "FL", 48000, 3400, 26, 39000, 2800, 21, "fl_secondary"),
        _row("TRK-016", "DRY_VAN", "77037", "TX", 48000, 3400, 26, 10000, 700, 4, "tx_tight_turn"),
        _row("TRK-017", "DRY_VAN", "92154", "CA", 48000, 3400, 26, 32000, 2400, 17, "ca_border_lane"),
        _row("TRK-018", "DRY_VAN", "97217", "OR", 48000, 3400, 26, 41000, 2950, 22, "pacific_nw"),
        _row("TRK-019", "DRY_VAN", "49512", "MI", 48000, 3400, 26, 28000, 1900, 14, "mi_regional"),
        _row("TRK-020", "UNKNOWN", "08817", "NJ", 48000, 3400, 26, 40000, 2900, 21, "equipment_unknown_matches_most"),
    ]


def _row(
    tractor_id: str,
    equipment: str,
    postal: str,
    region: str,
    max_w: float,
    max_c: float,
    max_p: float,
    av_w: float,
    av_c: float,
    av_p: float,
    note: str,
) -> dict[str, Any]:
    return {
        "tractor_id": tractor_id,
        "equipment_type": equipment,
        "domicile_postal": postal,
        "domicile_region": region,
        "mock_trailer_max_weight_lb": max_w,
        "mock_trailer_max_cube_cuft": max_c,
        "mock_trailer_max_pallet_positions": max_p,
        "mock_available_weight_lb": av_w,
        "mock_available_cube_cuft": av_c,
        "mock_available_pallet_positions": av_p,
        "mock_operational_situation": note,
    }

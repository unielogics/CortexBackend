"""Default audit / mock warehouse: UI address maps to parcel origin ZIP5 + engagement candidates.

When ``prep_center_candidate_warehouses.json`` is present (see ``prep_center_loader``), the
audit baseline is the designated Prep Center primary; otherwise Elizabeth, NJ mocks apply.

Financial source of truth for 3PL economics should be **billing + accounting** (hybrid is fine:
WMS billing lines + GL/accounting adjustments). Order/operational CSVs support activity and
allocation; they do not replace billed revenue/cost.
"""

from __future__ import annotations

from typing import Any

from unie_cortex.network.prep_center_loader import prep_center_baseline_row

_ELIZABETH = {
    "id": "elizabeth_primary",
    "postal": "07208",
    "label": "823 Westfield Ave, Elizabeth NJ 07208",
}

_pc_row = prep_center_baseline_row()
if _pc_row:
    AUDIT_BASELINE_ORIGIN_ZIP5 = str(_pc_row["postal"])
    AUDIT_BASELINE_WAREHOUSE_ID = str(_pc_row["id"])
    AUDIT_BASELINE_ADDRESS_LINE = str(_pc_row.get("label") or _pc_row["id"])
else:
    AUDIT_BASELINE_ORIGIN_ZIP5 = _ELIZABETH["postal"]
    AUDIT_BASELINE_WAREHOUSE_ID = _ELIZABETH["id"]
    AUDIT_BASELINE_ADDRESS_LINE = _ELIZABETH["label"]


def baseline_candidate_warehouses() -> list[dict[str, Any]]:
    """Shape matches ``EngagementNetworkContextBody.candidate_warehouses``."""
    row = prep_center_baseline_row()
    if row:
        return [
            {
                "id": row["id"],
                "postal": row["postal"],
                "label": row.get("label"),
            }
        ]
    return [
        {
            "id": _ELIZABETH["id"],
            "postal": _ELIZABETH["postal"],
            "label": _ELIZABETH["label"],
        }
    ]

"""Read-only registry of mock network assets for UI parity with planning/compare scripts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from unie_cortex.spine.fixture_warehouse_baseline import (
    AUDIT_BASELINE_ADDRESS_LINE,
    AUDIT_BASELINE_ORIGIN_ZIP5,
    AUDIT_BASELINE_WAREHOUSE_ID,
    baseline_candidate_warehouses,
)

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def load_marketplace_fee_reference() -> dict[str, Any]:
    """Amazon US referral bucket reference for Intelligence Network + seller fee copy (JSON source of truth)."""
    path = _DATA_DIR / "amazon_us_referral_reference_v1.json"
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def build_mock_network_reference() -> dict[str, Any]:
    """
    Single payload for Intelligence Network pages: audit baseline, script defaults,
    and pointers to live /v1/network routes.
    """
    blitz_multi_dc_preview = {
        "note": "Default nodes used in scripts/run_blitz_full_pipeline.py for POST /v1/assessment/multi-dc-preview",
        "warehouses": [
            {"id": "W-CA", "lat": 34.05, "lon": -118.25, "daily_outbound_cuft": 1200},
            {"id": "W-TX", "lat": 32.78, "lon": -96.80, "daily_outbound_cuft": 900},
            {"id": "W-NJ", "lat": 40.72, "lon": -74.17, "daily_outbound_cuft": 800},
        ],
        "lanes": [
            {"from_id": "W-CA", "to_id": "W-TX", "avg_cost_per_cuft": 0.42, "utilization_pct": 55},
            {"from_id": "W-TX", "to_id": "W-NJ", "avg_cost_per_cuft": 0.38, "utilization_pct": 72},
            {"from_id": "W-CA", "to_id": "W-NJ", "avg_cost_per_cuft": 0.51, "utilization_pct": 48},
        ],
    }
    blitz_compare_v2 = {
        "note": "Origins/receive_nodes/linehaul in run_blitz_full_pipeline.py when planning-run is absent",
        "origins": [
            {"postal": "90001", "warehouse_id": "FBM-WEST"},
            {"postal": "75201", "warehouse_id": "FBM-CENTRAL"},
            {"postal": "07001", "warehouse_id": "FBM-EAST"},
        ],
        "receive_nodes": [
            {"postal": "30309", "warehouse_id": "RCV-ATL"},
            {"postal": "75201", "warehouse_id": "RCV-DAL"},
            {"postal": "07001", "warehouse_id": "RCV-NJ"},
        ],
        "linehaul_origin_postal": "75201",
    }
    ref = load_marketplace_fee_reference()
    return {
        "schema_version": "mock_network_reference_v1",
        "marketplace_fee_reference": ref,
        "audit_baseline": {
            "warehouse_id": AUDIT_BASELINE_WAREHOUSE_ID,
            "origin_zip5": AUDIT_BASELINE_ORIGIN_ZIP5,
            "address_line": AUDIT_BASELINE_ADDRESS_LINE,
            "candidate_warehouses": baseline_candidate_warehouses(),
        },
        "blitz_script_defaults": {
            "multi_dc_preview": blitz_multi_dc_preview,
            "compare_v2_scenario": blitz_compare_v2,
        },
        "api_hints": {
            "capabilities": "GET /v1/network/capabilities",
            "pricing_profiles_list": "GET /v1/network/warehouse-pricing-profiles",
            "pricing_profile_detail": "GET /v1/network/warehouse-pricing-profiles/{profile_id}",
            "mock_reference": "GET /v1/network/mock-reference",
            "marketplace_fee_reference": "GET /v1/network/marketplace-fee-reference",
        },
    }

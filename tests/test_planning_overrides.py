"""Planning velocity overrides and request-body seller id merge."""

from unie_cortex.services.planning_overrides import (
    apply_planning_monthly_units_overrides,
    merge_planning_seller_inputs,
)


def test_merge_planning_seller_body_wins():
    row = {"sku": "S1", "extra": {"marketplace_seller_id": "OLD"}}
    si = merge_planning_seller_inputs(row, "S1", {"S1": "NEW"})
    assert si["marketplace_seller_id"] == "NEW"
    assert si.get("planning_marketplace_seller_id_source") == "request_body_by_sku"


def test_merge_planning_seller_falls_back_catalog():
    row = {"sku": "S1", "extra": {"marketplace_seller_id": "CAT"}}
    si = merge_planning_seller_inputs(row, "S1", None)
    assert si["marketplace_seller_id"] == "CAT"


def test_monthly_override_scales_band():
    demand = {
        "S1": {
            "monthly_units_est_mid": 100.0,
            "monthly_units_est_low": 75.0,
            "monthly_units_est_high": 133.0,
        }
    }
    meta = apply_planning_monthly_units_overrides(demand, {"S1": 50.0})
    assert "S1" in meta["applied"]
    assert demand["S1"]["monthly_units_est_mid"] == 50.0
    assert demand["S1"]["monthly_units_est_low"] == 37.5
    assert demand["S1"]["monthly_units_est_high"] == 66.5
    assert demand["S1"]["planning_monthly_units_override"]["user_monthly_units_mid"] == 50.0

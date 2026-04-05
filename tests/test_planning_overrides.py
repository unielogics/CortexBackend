"""Planning velocity overrides and request-body seller id merge."""

from unie_cortex.services.planning_overrides import (
    apply_planning_monthly_units_overrides,
    integerize_monthly_unit_fields_in_demand_by_sku,
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
    meta = apply_planning_monthly_units_overrides(demand, {"S1": 200.0})
    assert "S1" in meta["applied"]
    integerize_monthly_unit_fields_in_demand_by_sku(demand)
    assert demand["S1"]["monthly_units_est_mid"] == 200
    assert demand["S1"]["monthly_units_est_low"] == 150
    assert demand["S1"]["monthly_units_est_high"] == 266
    assert demand["S1"]["planning_monthly_units_override"]["user_monthly_units_mid"] == 200


def test_monthly_override_below_minimum_skipped():
    demand = {"S1": {"monthly_units_est_mid": 100.0}}
    meta = apply_planning_monthly_units_overrides(demand, {"S1": 100.0})
    assert "S1" not in meta["applied"]
    assert any(
        s.get("sku") == "S1" and s.get("reason") == "below_manual_override_minimum" for s in meta["skipped"]
    )
    assert demand["S1"]["monthly_units_est_mid"] == 100.0

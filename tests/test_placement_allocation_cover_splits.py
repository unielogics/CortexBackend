"""Cover split in demand_by_sku follows allocation monthly flows (not even divide)."""

from __future__ import annotations

from unie_cortex.services.placement_summary import (
    apply_inventory_cover_splits_from_allocation,
    build_inventory_placement_summary,
)


def test_cover_split_follows_allocation_weights_not_even():
    inv = build_inventory_placement_summary(
        asin="B0TEST",
        title="T",
        product_origin_postal="07055",
        monthly_units_est_mid=360.0,
        target_days_cover=75.0,
        warehouse_nodes=[
            {"warehouse_id": "NJ", "postal": "07001"},
            {"warehouse_id": "FL", "postal": "33101"},
        ],
    )
    assert inv["assumptions_version"] == "inventory_placement_summary_v1"
    total_cover = inv["suggested_total_units_for_target_cover"]
    assert total_cover and total_cover > 0
    even_splits = inv["warehouse_splits"]
    assert len(even_splits) == 2
    # v1 even split
    assert even_splits[0]["suggested_units_for_target_cover"] == even_splits[1]["suggested_units_for_target_cover"]

    demand = {
        "SKU1": {
            "sku": "SKU1",
            "inventory_placement_summary": inv,
        }
    }
    allocation = {
        "lines": [
            {
                "sku": "SKU1",
                "placement": [
                    {"warehouse_id": "NJ", "recommended_monthly_units": 176},
                    {"warehouse_id": "FL", "recommended_monthly_units": 184},
                ],
            }
        ]
    }
    apply_inventory_cover_splits_from_allocation(demand, allocation)
    inv2 = demand["SKU1"]["inventory_placement_summary"]
    assert inv2["cover_split_basis"] == "allocation_monthly_flow_integer_split"
    assert inv2["assumptions_version"] == "inventory_placement_summary_v2"
    splits = inv2["warehouse_splits"]
    assert len(splits) == 2
    a = next(s for s in splits if s["warehouse_id"] == "NJ")
    b = next(s for s in splits if s["warehouse_id"] == "FL")
    assert a["suggested_units_for_target_cover"] + b["suggested_units_for_target_cover"] == total_cover
    assert a["suggested_units_for_target_cover"] != b["suggested_units_for_target_cover"]
    assert a["allocation_monthly_flow_units"] == 176
    assert b["allocation_monthly_flow_units"] == 184


def test_zero_monthly_flow_falls_back_to_equal_shares_for_cover():
    inv = build_inventory_placement_summary(
        asin="B0",
        title=None,
        product_origin_postal="10001",
        monthly_units_est_mid=100.0,
        target_days_cover=30.0,
        warehouse_nodes=[
            {"warehouse_id": "A", "postal": "10001"},
            {"warehouse_id": "B", "postal": "20002"},
        ],
    )
    total_cover = inv["suggested_total_units_for_target_cover"]
    demand = {"S": {"sku": "S", "inventory_placement_summary": inv}}
    allocation = {
        "lines": [
            {
                "sku": "S",
                "placement": [
                    {"warehouse_id": "A", "recommended_monthly_units": 0},
                    {"warehouse_id": "B", "recommended_monthly_units": 0},
                ],
            }
        ]
    }
    apply_inventory_cover_splits_from_allocation(demand, allocation)
    splits = demand["S"]["inventory_placement_summary"]["warehouse_splits"]
    assert sum(s["suggested_units_for_target_cover"] for s in splits) == total_cover
    assert splits[0]["suggested_units_for_target_cover"] == splits[1]["suggested_units_for_target_cover"]

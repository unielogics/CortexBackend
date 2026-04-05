"""cuOpt intelligence fusion: allocation cuft, parcel means, economics → warehouse rows."""

from __future__ import annotations

from unie_cortex.services.cuopt_intelligence_fusion import (
    enrich_cuopt_warehouse_rows,
    fulfillment_monthly_usd_proxy_by_warehouse,
    monthly_allocated_cuft_by_warehouse,
    sku_to_cube_cuft_map,
)


def test_monthly_cuft_from_allocation():
    alloc = {
        "lines": [
            {
                "sku": "A",
                "placement": [
                    {"warehouse_id": "w1", "recommended_monthly_units": 100},
                    {"warehouse_id": "w2", "recommended_monthly_units": 50},
                ],
            }
        ]
    }
    cube = {"A": 2.0}
    m = monthly_allocated_cuft_by_warehouse(alloc, cube)
    assert m["w1"] == 200.0
    assert m["w2"] == 100.0


def test_fulfillment_proxy_from_economics():
    econ = {
        "per_sku": [
            {
                "monthly_demand_units": 10.0,
                "cost_detail_for_downstream_systems": {
                    "per_warehouse_fulfillment": {
                        "rows": [
                            {
                                "warehouse_id": "w1",
                                "estimated_fulfillment_handling_benchmark_usd_per_unit_sold_contribution": 2.0,
                            },
                            {
                                "warehouse_id": "w2",
                                "estimated_fulfillment_handling_benchmark_usd_per_unit_sold_contribution": 3.0,
                            },
                        ]
                    }
                },
            }
        ]
    }
    o = fulfillment_monthly_usd_proxy_by_warehouse(econ)
    assert o["w1"] == 20.0
    assert o["w2"] == 30.0


def test_enrich_merges_into_cuopt_rows():
    rows = [{"id": "w1", "lat": 1.0, "lon": 2.0}, {"id": "w2", "lat": 3.0, "lon": 4.0}]
    out, meta = enrich_cuopt_warehouse_rows(
        rows,
        monthly_cuft_by_wh={"w1": 10.0},
        parcel_usd_by_wh={"w2": 8.5},
        fulfillment_monthly_usd_by_wh={"w1": 100.0},
    )
    assert out[0]["allocated_monthly_cuft"] == 10.0
    assert out[0]["fulfillment_monthly_usd_proxy"] == 100.0
    assert out[1]["mean_mock_parcel_usd"] == 8.5
    assert meta["warehouses_with_allocation_cuft"] == 1


def test_sku_to_cube_from_alloc_inputs():
    m = sku_to_cube_cuft_map([{"sku": "x", "cube_cuft": 1.5}])
    assert m["x"] == 1.5

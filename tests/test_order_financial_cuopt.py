"""Seller order-planning cuOpt tri-modal wiring (no live NVIDIA)."""

from __future__ import annotations

import pytest

from unie_cortex.services.order_financial_cuopt import run_order_planning_cuopt_tri_modal
from unie_cortex.services.order_financial_planning import build_cuopt_warehouse_rows_for_order_planning


@pytest.mark.asyncio
async def test_cuopt_skipped_when_fewer_than_two_warehouses():
    scen = {
        "status": "complete",
        "qty": 100,
        "warehouse_network": {
            "selected_warehouses": [{"id": "only1", "postal": "07055"}],
            "lanes": [],
            "hub_warehouse_id": "only1",
        },
    }
    out = await run_order_planning_cuopt_tri_modal(
        scenario_fbm=scen,
        placement_mock_rate_grids=None,
        analysis={"order_velocity_enrichment": {"estimated_monthly_demand_units_for_planning": 50}},
        weight_lb_per_unit=1.0,
        length_in=9.0,
        width_in=7.0,
        height_in=5.0,
        include_overview=True,
        include_nvidia_layer=False,
    )
    assert out is None


@pytest.mark.asyncio
async def test_cuopt_returns_tri_modal_shape_when_two_warehouses(monkeypatch):
    async def fake_build(**kwargs):
        src = str(kwargs.get("solver_network_source") or "")
        assert src.startswith("order_financial_planning_fbm")
        assert len(kwargs.get("warehouses") or []) == 2
        return {"schema_version": "item_intelligence_multi_dc_tri_modal_v1", "status": "stub"}

    monkeypatch.setattr(
        "unie_cortex.services.order_financial_cuopt.build_item_intelligence_multi_dc_tri_modal",
        fake_build,
    )
    scen = {
        "status": "complete",
        "qty": 200,
        "warehouse_network": {
            "selected_warehouses": [
                {"id": "hub", "postal": "07055"},
                {"id": "spoke", "postal": "90001"},
            ],
            "lanes": [{"from_id": "hub", "to_id": "spoke", "cost_per_lb": 0.12}],
            "hub_warehouse_id": "hub",
        },
    }
    out = await run_order_planning_cuopt_tri_modal(
        scenario_fbm=scen,
        placement_mock_rate_grids={"status": "complete", "mean_mock_parcel_usd_by_warehouse": {"hub": 8.0}},
        analysis={"order_velocity_enrichment": {"estimated_monthly_demand_units_for_planning": 120}},
        weight_lb_per_unit=2.0,
        length_in=10.0,
        width_in=8.0,
        height_in=6.0,
        include_overview=True,
        include_nvidia_layer=False,
    )
    assert out is not None
    assert out.get("schema_version") == "item_intelligence_multi_dc_tri_modal_v1"


def test_cuopt_rows_use_expanded_grid_when_single_selected_warehouse(monkeypatch):
    """National rate-shop mean map can supply ≥2 DCs while smart network keeps one linehaul node."""
    net = {
        "selected_warehouses": [{"id": "only_hub", "postal": "07055", "target_share_pct": 100.0}],
        "lanes": [],
        "hub_warehouse_id": "only_hub",
    }
    grid = {
        "status": "complete",
        "mean_mock_parcel_usd_by_warehouse": {"only_hub": 8.0, "wh_ca": 9.5},
        "warehouse_grids": {
            "only_hub": [{"origin_postal": "07055"}],
            "wh_ca": [{"origin_postal": "90001"}],
        },
        "suggested_target_share_pct_by_warehouse": {"only_hub": 55.0, "wh_ca": 45.0},
    }
    rows, tag = build_cuopt_warehouse_rows_for_order_planning(
        warehouse_network=net,
        placement_mock_rate_grids=grid,
        engagement_network_context=None,
    )
    assert tag == "order_financial_planning_fbm_national_rate_shop_pool"
    assert len(rows) == 2
    ids = {r["id"] for r in rows}
    assert ids == {"only_hub", "wh_ca"}

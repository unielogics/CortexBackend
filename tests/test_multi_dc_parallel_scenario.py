"""multi_dc_parallel_scenario branch: grids + allocation + economics + FNC for multi-DC option."""

from __future__ import annotations

import pytest

from unie_cortex.network.us_state_demand_share import build_blended_state_demand_weights_from_labels
from unie_cortex.services.intelligence_run import _build_multi_dc_parallel_scenario


class _MockTaxStore:
    async def tenant_sales_tax_nexus_list(self, tenant_id: str) -> list[str]:
        return []

    async def tax_jurisdiction_get(self, *args, **kwargs):
        return None


@pytest.mark.asyncio
async def test_multi_dc_parallel_scenario_linehaul_positive_with_two_nodes():
    blended, label_meta = build_blended_state_demand_weights_from_labels([])
    wno = {
        "status": "complete",
        "options": [
            {
                "option_key": "multi_dc",
                "selected_warehouses": [
                    {"id": "reg_ne", "postal": "07102", "target_share_pct": 50.0},
                    {"id": "reg_se", "postal": "30303", "target_share_pct": 50.0},
                ],
                "lanes": [{"from_id": "reg_ne", "to_id": "reg_se", "cost_per_lb": 0.15}],
                "hub_warehouse_id": "reg_ne",
            }
        ],
    }
    alloc_inputs = [
        {"sku": "SKU1", "monthly_units": 800.0, "weight_lb": 2.0, "cube_cuft": 0.25},
    ]
    intel = {
        "SKU1": {
            "sku": "SKU1",
            "avg_weight_lb": 2.0,
            "length_in": 10.0,
            "width_in": 8.0,
            "height_in": 6.0,
        }
    }
    demand_by_sku = {
        "SKU1": {"sku": "SKU1", "monthly_units_est_mid": 800.0, "status": "complete"},
    }
    catalog_by_sku = {
        "SKU1": {
            "sku": "SKU1",
            "weight_lb": 2.0,
            "length_in": 10.0,
            "width_in": 8.0,
            "height_in": 6.0,
        }
    }
    out = await _build_multi_dc_parallel_scenario(
        store=_MockTaxStore(),  # type: ignore[arg-type]
        tenant_id="t1",
        warehouse_network_recommendation_options=wno,
        blended_state_weights=blended,
        label_demand_weight_meta=label_meta,
        median_w=2.0,
        n_mock=48,
        tie=0.07,
        assign_mode="min_mock_parcel",
        alloc_inputs=alloc_inputs,
        merged_intel_by_sku=intel,
        demand_by_sku=demand_by_sku,
        catalog_by_sku=catalog_by_sku,
        flow_model="hub_spoke_rate_card_v1",
        default_pid="profile_nj_v1",
        fee_recv=0.35,
        fee_out=0.12,
        fee_stor=0.02,
        min_xfer=100.0,
        max_m_xfer=12,
        seller_lh=True,
        lh_mult=1.0,
        nexus_states=[],
    )
    assert out["status"] == "complete"
    assert out["source_option_key"] == "multi_dc"
    assert out["allocation"]["status"] == "complete"
    econ = out["landed_cost_economics"]
    per_sku = econ.get("per_sku") or []
    row = next((r for r in per_sku if isinstance(r, dict) and r.get("sku") == "SKU1"), None) or {}
    cd = row.get("cost_detail_for_downstream_systems") or {}
    xfer = cd.get("inter_warehouse_positioning") or {}
    lh_pu = xfer.get("linehaul_usd_per_unit_sold")
    assert lh_pu is not None
    assert float(lh_pu) > 0.0
    fnc = out["fulfillment_network_comparison"]
    frows = fnc.get("per_sku") or []
    hit = next((r for r in frows if isinstance(r, dict) and r.get("sku") == "SKU1"), None)
    assert hit is not None


@pytest.mark.asyncio
async def test_multi_dc_parallel_scenario_skipped_one_warehouse():
    blended, label_meta = build_blended_state_demand_weights_from_labels([])
    wno = {
        "status": "complete",
        "options": [
            {
                "option_key": "multi_dc",
                "selected_warehouses": [{"id": "reg_ne", "postal": "07102", "target_share_pct": 100.0}],
                "lanes": [],
                "hub_warehouse_id": "reg_ne",
            }
        ],
    }
    out = await _build_multi_dc_parallel_scenario(
        store=_MockTaxStore(),  # type: ignore[arg-type]
        tenant_id="t1",
        warehouse_network_recommendation_options=wno,
        blended_state_weights=blended,
        label_demand_weight_meta=label_meta,
        median_w=2.0,
        n_mock=48,
        tie=0.07,
        assign_mode="min_mock_parcel",
        alloc_inputs=[],
        merged_intel_by_sku={},
        demand_by_sku={},
        catalog_by_sku={},
        flow_model="hub_spoke_rate_card_v1",
        default_pid="profile_nj_v1",
        fee_recv=0.35,
        fee_out=0.12,
        fee_stor=0.02,
        min_xfer=100.0,
        max_m_xfer=12,
        seller_lh=True,
        lh_mult=1.0,
        nexus_states=[],
    )
    assert out["status"] == "skipped"
    assert out.get("reason") == "fewer_than_two_warehouses"

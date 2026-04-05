"""Seller mixed-pallet fraction linehaul and consolidated-path pallet assembly."""

from __future__ import annotations

import asyncio

import pytest

from unie_cortex.network.pallet_defaults import reference_pallet_cuft
from unie_cortex.network.scenario_fbm_warehouse_fees import build_fbm_consolidated_path_warehouse_breakdown
from unie_cortex.network.scenarios_integrated import compare_scenario_v2_integrated
from unie_cortex.network.seller_mixed_pallet_linehaul import (
    build_seller_consolidated_linehaul_leg,
    nominal_mixed_pallet_weight_lb,
    pallet_slot_fraction,
)
from unie_cortex.services.allocation_v1 import allocate_skus
from unie_cortex.services.order_financial_planning import run_integrated_compare_for_order_planning


def test_pallet_slot_fraction_edges():
    slot = reference_pallet_cuft()
    assert pallet_slot_fraction(total_cuft=0.0, slot_cuft=slot) == 0.0
    assert pallet_slot_fraction(total_cuft=slot * 2, slot_cuft=slot) == 1.0
    assert pallet_slot_fraction(total_cuft=slot * 0.5, slot_cuft=slot) == pytest.approx(0.5)


def test_nominal_mixed_pallet_weight_clamp():
    assert nominal_mixed_pallet_weight_lb(100, 0.01, lo=500, hi=2500) == 2500.0
    assert nominal_mixed_pallet_weight_lb(50, 0.5, lo=500, hi=2500) == 500.0
    assert nominal_mixed_pallet_weight_lb(400, 0.8, lo=500, hi=2500) == 500.0


def test_build_seller_linehaul_ltl_scales_by_fraction():
    slot = reference_pallet_cuft()
    total_cuft = slot * 0.25
    total_w = 200.0
    leg = build_seller_consolidated_linehaul_leg(
        mode="ltl",
        qty=10,
        total_w=total_w,
        total_cuft=total_cuft,
        consolidated_linehaul_cost_multiplier=1.0,
    )
    assert leg["seller_mixed_pallet_basis_v1"] is True
    assert leg["pallet_slot_fraction"] == pytest.approx(0.25, rel=1e-5)
    base = float(leg["baseline_full_reference_pallet_usd"])
    assert leg["total_usd"] == pytest.approx(round(0.25 * base, 2), rel=1e-5)


def test_build_seller_linehaul_ftl_branch():
    leg = build_seller_consolidated_linehaul_leg(
        mode="ftl",
        qty=5,
        total_w=800.0,
        total_cuft=reference_pallet_cuft() * 0.1,
        consolidated_linehaul_cost_multiplier=1.0,
    )
    assert leg["mode"] == "ftl"
    assert leg["source"] == "network_seller_mixed_pallet_linehaul_v1"
    frac = float(leg["pallet_slot_fraction"])
    base = float(leg["baseline_full_reference_pallet_usd"])
    assert leg["total_usd"] == pytest.approx(round(frac * base, 2), rel=1e-4)


@pytest.mark.asyncio
async def test_compare_integrated_seller_flag_sets_linehaul_basis():
    out = await compare_scenario_v2_integrated(
        weight_lb_per_unit=2.0,
        length_in=9.0,
        width_in=7.0,
        height_in=5.0,
        qty=20,
        origins=[{"postal": "07001", "warehouse_id": "NJ1"}],
        receive_nodes=[{"postal": "07001", "warehouse_id": "NJ1", "pricing_profile_id": "profile_nj_v1"}],
        linehaul_origin_postal="07001",
        destinations=[{"postal": "10001"}],
        carriers_fallback=["usps"],
        seller_mixed_pallet_linehaul=True,
        consolidated_linehaul_cost_multiplier=1.0,
        direct_use_integrated=False,
        consolidated_parcel_use_integrated=False,
    )
    assert out.get("status") == "complete"
    chosen = (out.get("consolidated") or {}).get("chosen") or {}
    lh = chosen.get("linehaul_leg") or {}
    assert lh.get("seller_mixed_pallet_basis_v1") is True
    assert "pallet_slot_fraction" in lh
    assert out.get("consolidated_linehaul_economics", {}).get("seller_mixed_pallet_linehaul_applied") is True
    cpr = out.get("cube_and_pallet_reference") or {}
    assert "analyzed_qty_total_cuft" in cpr
    assert "fraction_of_reference_pallet_slot" in cpr
    assert cpr["fraction_of_reference_pallet_slot"] == lh.get("pallet_slot_fraction")


def test_fbm_consolidated_pallet_assembly_from_profile():
    row = build_fbm_consolidated_path_warehouse_breakdown(
        receive_node={"warehouse_id": "NJ1", "postal": "07001", "pricing_profile_id": "profile_nj_v1"},
        qty=40,
        length_in=9.0,
        width_in=7.0,
        height_in=5.0,
    )
    asm = row.get("pallet_assembly_fee") or {}
    recv = row.get("inbound_receive_fee") or {}
    per = float(asm.get("per_pallet_assembly_usd") or 0)
    assert per == pytest.approx(19.0)
    share = float(recv.get("pallet_slot_share_est") or 0)
    assert asm.get("pallet_slot_share_est") == pytest.approx(share, rel=1e-5)
    expected_asm = round(per * share, 2)
    assert float(asm.get("pallet_assembly_subtotal_usd") or 0) == pytest.approx(expected_asm, rel=1e-4)
    tw = float(row.get("total_warehouse_fbm_usd") or 0)
    recv_sub = float(recv.get("receive_subtotal_usd") or 0)
    out_sub = float((row.get("outbound_pick_pack") or {}).get("total_outbound_handling_usd") or 0)
    assert tw == pytest.approx(round(recv_sub + out_sub + expected_asm, 2), rel=1e-4)


def test_allocate_skus_seller_mixed_imputes_cube_when_zero_but_weight_present():
    skus = [{"sku": "S1", "monthly_units": 100, "weight_lb": 2.0, "cube_cuft": 0.0}]
    wh = [{"id": "hub", "target_share_pct": 50}, {"id": "east", "target_share_pct": 50}]
    lanes = [{"from_id": "hub", "to_id": "east", "cost_per_lb": 0.1}]
    out = allocate_skus(
        skus,
        wh,
        lanes,
        hub_id="hub",
        seller_mixed_pallet_linehaul=True,
        consolidated_linehaul_cost_multiplier=1.0,
    )
    assert out["transfer_linehaul_model"] == "seller_mixed_pallet_linehaul_v1"
    leg = out["lines"][0]["transfer_from_hub"][0]
    assert leg["transfer_pricing"]["method"] == "seller_mixed_pallet_linehaul_v1"
    assert leg["transfer_pricing"].get("cube_imputed_from_monthly_leg_weight_lb") is True
    assert "linehaul_mode" in leg["transfer_pricing"]


def test_allocate_skus_seller_mixed_pallet_matches_transfer_model():
    skus = [{"sku": "S1", "monthly_units": 100, "weight_lb": 2.0, "cube_cuft": 0.5}]
    wh = [{"id": "hub", "target_share_pct": 50}, {"id": "east", "target_share_pct": 50}]
    lanes = [{"from_id": "hub", "to_id": "east", "cost_per_lb": 0.1}]
    legacy = allocate_skus(skus, wh, lanes, hub_id="hub", seller_mixed_pallet_linehaul=False)
    seller = allocate_skus(
        skus,
        wh,
        lanes,
        hub_id="hub",
        seller_mixed_pallet_linehaul=True,
        consolidated_linehaul_cost_multiplier=1.0,
    )
    assert legacy["transfer_linehaul_model"] == "lane_dollar_per_lb_v1"
    assert seller["transfer_linehaul_model"] == "seller_mixed_pallet_linehaul_v1"
    assert seller["seller_mixed_pallet_linehaul_applied"] is True
    leg = seller["lines"][0]["transfer_from_hub"][0]
    assert leg["transfer_pricing"]["method"] == "seller_mixed_pallet_linehaul_v1"
    assert legacy["total_transfer_cost_est_usd"] != seller["total_transfer_cost_est_usd"]


def test_run_integrated_compare_order_planning_uses_seller_linehaul_by_default():
    rows = [
        {
            "order_date_iso": "2025-04-01",
            "sku": "S1",
            "quantity": 30,
            "ship_to_postal": "10001",
            "revenue_usd": 25.0,
        }
    ]
    out = asyncio.run(
        run_integrated_compare_for_order_planning(
            rows=rows,
            fulfillment_mode="fbm",
            max_scenario_qty=80,
        )
    )
    assert out.get("status") == "complete"
    assert (out.get("scenario_inputs") or {}).get("seller_mixed_pallet_linehaul") is True
    chosen = (out.get("consolidated") or {}).get("chosen") or {}
    assert (chosen.get("linehaul_leg") or {}).get("seller_mixed_pallet_basis_v1") is True
    wh = chosen.get("fbm_warehouse_breakdown") or {}
    assert "pallet_assembly_fee" in wh

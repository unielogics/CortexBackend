"""FBA supplier inbound rules and planning comparison matrix."""

import asyncio

from unie_cortex.services.fba_supplier_inbound import (
    postal_great_circle_distance_miles,
    supplier_inbound_covered_by_rules,
)
from unie_cortex.services.order_financial_analysis import analyze_order_financial_facts
from unie_cortex.services.order_financial_planning import (
    build_planning_comparison_matrix_v1,
    compute_fba_inbound_for_planning,
)


def test_postal_distance_miles_known_hubs():
    # Newark NJ hub ZIP to Los Angeles CA hub ZIP — expect hundreds of miles
    mi, err = postal_great_circle_distance_miles("07102", "90012")
    assert err is None
    assert mi is not None
    assert mi > 200


def test_supplier_inbound_free_radius_or_threshold():
    r = supplier_inbound_covered_by_rules(
        distance_miles=10.0,
        free_mile_radius_mi=50.0,
        qualifying_order_value_usd=100.0,
        purchase_threshold_usd=500.0,
        require_both_for_free_inbound=False,
    )
    assert r["covered_by_free_radius"] is True
    assert r["supplier_inbound_effectively_free"] is True

    r2 = supplier_inbound_covered_by_rules(
        distance_miles=500.0,
        free_mile_radius_mi=50.0,
        qualifying_order_value_usd=1000.0,
        purchase_threshold_usd=500.0,
        require_both_for_free_inbound=False,
    )
    assert r2["covered_by_purchase_threshold"] is True
    assert r2["supplier_inbound_effectively_free"] is True

    r3 = supplier_inbound_covered_by_rules(
        distance_miles=500.0,
        free_mile_radius_mi=50.0,
        qualifying_order_value_usd=100.0,
        purchase_threshold_usd=500.0,
        require_both_for_free_inbound=True,
    )
    assert r3["supplier_inbound_effectively_free"] is False


def test_estimate_supplier_leg_rate_shops_when_not_covered():
    from unie_cortex.services.fba_supplier_inbound import estimate_supplier_to_prep_leg

    async def _run():
        return await estimate_supplier_to_prep_leg(
            supplier_ship_from_postal="10001",
            prep_receive_postal="90012",
            qty=50,
            weight_lb_per_unit=1.0,
            length_in=9,
            width_in=7,
            height_in=5,
            free_mile_radius_mi=1.0,
            purchase_threshold_usd=1_000_000.0,
            qualifying_order_value_usd=1.0,
            require_both_for_free_inbound=False,
            use_integrated_parcel=False,
        )

    leg = asyncio.run(_run())
    assert leg["status"] == "complete"
    assert leg["chosen_mode"] in ("parcel", "ltl_mock")
    assert float(leg["chosen_total_usd"] or 0) >= 0


def test_planning_comparison_matrix_four_columns():
    rows = [
        {
            "revenue_usd": 400.0,
            "marketplace_fees_usd": 80.0,
            "referral_fees_modeled_usd": 40.0,
            "total_fees_usd": 100.0,
            "profit_usd": 120.0,
            "quantity": 4.0,
            "prep_cost_usd": 2.0,
            "inbound_cost_usd": 1.0,
        }
    ]
    analysis = analyze_order_financial_facts(rows)
    fbm = {
        "status": "complete",
        "qty": 4,
        "fulfillment_mode": "fbm",
        "direct": {"total_usd": 30.0, "transport_parcel_total_usd": 25.0, "legs": []},
        "consolidated": {
            "total_usd": 35.0,
            "transport_linehaul_plus_parcel_total_usd": 32.0,
            "chosen": {
                "receive_postal": "07001",
                "warehouse_id": "RCV-1",
                "linehaul_leg": {"total_usd": 10.0},
                "parcel_total_usd": 22.0,
            },
        },
        "fbm_full_financial_breakdown": {
            "direct": {
                "warehouse_fbm_breakdown": {
                    "total_warehouse_fbm_usd": 5.0,
                }
            },
            "consolidated": {
                "warehouse_fbm_breakdown": {
                    "inbound_receive_fee": {"receive_subtotal_usd": 3.0},
                    "outbound_pick_pack": {"total_outbound_handling_usd": 4.0},
                }
            },
        },
    }
    fba = {
        "status": "complete",
        "qty": 4,
        "fulfillment_mode": "fba",
        "consolidated": {
            "total_usd": 40.0,
            "transport_linehaul_plus_parcel_total_usd": 40.0,
            "chosen": {"receive_postal": "07001"},
        },
        "direct": {"total_usd": 45.0},
        "fulfillment_mode_warehouse_overlay": {"max_per_unit_adder_usd_across_receive_nodes": 0.5},
    }
    m = build_planning_comparison_matrix_v1(
        analysis=analysis,
        scenario_fbm=fbm,
        scenario_fba=fba,
        fba_inbound_economics=None,
        csv_baseline_fulfillment="fba",
    )
    assert m["schema_version"] == "planning_comparison_matrix_v1"
    assert set(m["columns"].keys()) == {
        "current",
        "amazon_fba",
        "amazon_fbm_single",
        "amazon_fbm_multi",
    }
    assert isinstance(m.get("comparison_parity_notes"), list)
    assert isinstance(m.get("comparison_math_audit"), dict)
    codes = {n.get("code") for n in m["comparison_parity_notes"]}
    assert "fba_inbound_economics_missing" in codes
    assert "fbm_model_uncertainty" in codes
    cur = m["columns"]["current"]["line_items"]
    assert any(x["id"] == "marketplace_fees" for x in cur)


def test_compute_fba_inbound_attaches_stack():
    analysis = analyze_order_financial_facts(
        [
            {
                "revenue_usd": 200.0,
                "marketplace_fees_usd": 50.0,
                "referral_fees_modeled_usd": 10.0,
                "total_fees_usd": 60.0,
                "profit_usd": 50.0,
                "quantity": 2.0,
            }
        ]
    )
    fba = {
        "status": "complete",
        "qty": 2,
        "fulfillment_mode": "fba",
        "consolidated": {
            "total_usd": 10.0,
            "transport_linehaul_plus_parcel_total_usd": 10.0,
            "chosen": {"receive_postal": "07001"},
        },
        "direct": {"total_usd": 12.0},
        "fulfillment_mode_warehouse_overlay": {"max_per_unit_adder_usd_across_receive_nodes": 0.25},
    }
    async def _run():
        return await compute_fba_inbound_for_planning(
            scenario_fba=fba,
            analysis=analysis,
            inbound_from_supplier={
                "supplier_ship_from_postal": "10001",
                "free_mile_radius_mi": 0.0,
                "purchase_threshold_usd": 999999.0,
            },
            fba_prep_line_items=[{"label": "Bundling", "total_usd": 5.0}],
            qualifying_order_value_usd=1.0,
            weight_lb_per_unit=1.0,
            length_in=8,
            width_in=6,
            height_in=5,
            use_integrated_parcel=False,
        )

    fin = asyncio.run(_run())
    assert fin is not None
    assert fin["schema_version"] == "fba_inbound_economics_v1"
    assert fin["modeled_prep_center_stack_total_usd"] > 0

"""Phase 2: receiving-facility resolution + seller line-item allocation (Option A)."""

from __future__ import annotations

from unie_cortex.services.order_financial_planning import (
    build_receiving_facility_resolution_v1,
    build_seller_line_item_allocation_v1,
)


def test_build_receiving_facility_resolution_picks_closest_candidate():
    nc = {
        "product_origins_by_sku": {
            "A": {"source_postal": "10001", "source_city": "NYC"},
        },
        "candidate_warehouses": [
            {"id": "far-wh", "postal": "90012", "label": "Far West"},
            {"id": "near-wh", "postal": "07001", "label": "Near NJ"},
        ],
    }
    wn = {
        "selected_warehouses": [
            {"id": "user-origin-10001", "postal": "10001", "label": "User NYC"},
        ]
    }
    out = build_receiving_facility_resolution_v1(engagement_network_context=nc, warehouse_network=wn)
    assert out and out.get("schema_version") == "receiving_facility_resolution_v1"
    e = (out.get("by_user_origin_postal") or {}).get("10001")
    assert e is not None
    assert e.get("matched_warehouse_id") == "near-wh"
    assert "Near NJ" in (e.get("display_label") or "")
    assert "10001" in (e.get("display_label") or "")


def test_build_seller_line_item_allocation_splits_by_quantity_share():
    sku_rollup = {
        "schema_version": "order_financial_sku_rollup_v1",
        "rows": [
            {"identifier": "sku-a", "sku": "A", "asin": None, "quantity_total": 10.0, "revenue_usd_total": 100.0},
            {"identifier": "sku-b", "sku": "B", "asin": None, "quantity_total": 30.0, "revenue_usd_total": 200.0},
        ],
    }
    planning_matrix = {
        "scenario_qty_units": 40,
        "columns": {
            "amazon_fbm_multi": {
                "line_items": [
                    {
                        "id": "t1",
                        "category": "transport_carrier",
                        "total_usd": 40.0,
                        "include_in_grand_total": True,
                    },
                ],
            },
            "amazon_fba": {"line_items": []},
            "amazon_fbm_single": {"line_items": []},
        },
    }
    out = build_seller_line_item_allocation_v1(sku_rollup=sku_rollup, planning_matrix=planning_matrix)
    assert out and out.get("schema_version") == "seller_line_item_allocation_v1"
    rows = out.get("rows") or []
    assert len(rows) == 2
    by_id = {r["identifier"]: r for r in rows}
    a = by_id["sku-a"]["allocated"]["amazon_fbm_multi"]
    b = by_id["sku-b"]["allocated"]["amazon_fbm_multi"]
    assert a["grand_total_allocated_usd"] == 10.0  # 40 * 10/40
    assert b["grand_total_allocated_usd"] == 30.0  # 40 * 30/40
    assert a["by_category"]["transport_carrier"] == 10.0
    assert b["by_category"]["transport_carrier"] == 30.0

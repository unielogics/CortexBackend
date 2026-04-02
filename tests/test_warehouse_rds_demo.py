"""Demo Prep Center warehouse RDS bundle."""

from unie_cortex.services.warehouse_rds_demo import get_warehouse_rds_demo_bundle, reload_warehouse_rds_demo_cache


def test_demo_bundle_has_warehouses():
    reload_warehouse_rds_demo_cache()
    b = get_warehouse_rds_demo_bundle()
    assert b.get("status") == "complete"
    wh = b.get("warehouses")
    assert isinstance(wh, list) and len(wh) >= 1
    row0 = wh[0]
    assert isinstance(row0, dict)
    assert row0.get("warehouse_id") or row0.get("id")
    assert "pricing_json" in row0 or "postal" in row0

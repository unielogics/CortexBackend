"""Rate bucket, warehouse pricing mocks, cached hot-zip grid."""

from fastapi.testclient import TestClient

from unie_cortex.main import app
from unie_cortex.network.rate_bucket import physical_rate_bucket, rate_cache_key_parts
from unie_cortex.network.warehouse_pricing_mock import (
    estimate_partial_transfer_flow_mock,
    flat_landed_cost_inputs_from_profile,
    get_pricing_profile,
)


def test_physical_rate_bucket_rounding():
    # 2-inch dimension bins: 12.2/12.4→12, 8.9/9.0→8, 4.1/3.9→4; weight 6oz slabs
    b1 = physical_rate_bucket(12.2, 8.9, 4.1, 2.5)
    b2 = physical_rate_bucket(12.4, 9.0, 3.9, 2.6)
    assert b1 == b2
    _, k1 = rate_cache_key_parts(
        tenant_id="t1", bucket=b1, origin_postal="07001", dest_postal="90210", service_code=None
    )
    _, k2 = rate_cache_key_parts(
        tenant_id="t1", bucket=b2, origin_postal="07001", dest_postal="90210", service_code=None
    )
    assert k1 == k2


def test_partial_inbound_flow_mock():
    out = estimate_partial_transfer_flow_mock(
        from_profile_id="profile_nj_v1",
        to_profile_id="profile_ca_v1",
        qty_total=1000,
        fraction_to_transfer=0.3,
        weight_lb_per_unit=2.5,
        length_in=12,
        width_in=9,
        height_in=4,
        fulfillment_mode="mixed",
    )
    assert out["status"] == "complete"
    assert out["qty_transfer_to_secondary_est"] > 0
    assert out["total_estimated_usd"] > 0
    assert "summary" in out and "options" in out
    assert 2 <= len(out["options"]) <= 3
    xd = out["origin_crossdock"]
    assert xd["cross_dock_pallet_fee_usd"] >= 10.0
    assert xd["per_pallet_cross_dock_usd"] == 10.0
    assert "smart_billing" in (get_pricing_profile("profile_nj_v1") or {}).get("rate_card", {})


def test_hot_zip_grid_cache_hit_second_call():
    body = {
        "tenant_id": "test_tenant_rates",
        "warehouses": [{"postal": "07001", "warehouse_id": "NJ"}],
        "dest_postals": ["90210", "33101"],
        "weight_lb": 2.5,
        "length_in": 12,
        "width_in": 9,
        "height_in": 4,
        "use_cache": True,
    }
    with TestClient(app) as c:
        r1 = c.post("/v1/network/rate-shop/hot-zip-grid", json=body)
        assert r1.status_code == 200, r1.text
        j1 = r1.json()
        assert j1["status"] == "complete"
        assert len(j1["cells"]) == 2
        r2 = c.post("/v1/network/rate-shop/hot-zip-grid", json=body)
        j2 = r2.json()
        assert j2["cache_hits"] >= 2


def test_warehouse_pricing_profiles_endpoint():
    with TestClient(app) as c:
        r = c.get("/v1/network/warehouse-pricing-profiles")
        assert r.status_code == 200
        ids = {p["id"] for p in r.json()["profiles"]}
        assert "profile_nj_v1" in ids


def test_flat_landed_cost_inputs_from_profile():
    nj = flat_landed_cost_inputs_from_profile("profile_nj_v1")
    assert set(nj.keys()) == {
        "inbound_receiving_per_unit_usd",
        "outbound_handling_per_unit_usd",
        "storage_per_unit_month_usd",
    }
    assert nj["inbound_receiving_per_unit_usd"] > 0
    assert nj["outbound_handling_per_unit_usd"] > 0
    assert nj["storage_per_unit_month_usd"] > 0
    unknown = flat_landed_cost_inputs_from_profile("profile_does_not_exist")
    assert unknown["inbound_receiving_per_unit_usd"] == nj["inbound_receiving_per_unit_usd"]

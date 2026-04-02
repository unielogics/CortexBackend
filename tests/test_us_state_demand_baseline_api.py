from unie_cortex.network.us_state_demand_share import contiguous_state_demand_shares_normalized


def test_contiguous_baseline_count():
    d = contiguous_state_demand_shares_normalized()
    assert len(d) == 48
    s = sum(d.values())
    assert abs(s - 1.0) < 1e-6
    assert d.get("CA", 0) > d.get("WY", 0)

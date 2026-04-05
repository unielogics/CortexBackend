"""cuOpt tri-modal should use recommended multi-DC graph when the request is single-DC."""

from __future__ import annotations

from unie_cortex.services.intelligence_run import _network_inputs_for_cuopt_tri_modal


def test_cuopt_network_prefers_complete_parallel_scenario():
    request_wh = [{"id": "seed_only", "postal": "07055", "target_share_pct": 100.0}]
    parallel = {
        "status": "complete",
        "warehouses": [
            {"id": "hub", "postal": "07055"},
            {"id": "spoke", "postal": "30303"},
        ],
        "lanes": [{"from_id": "hub", "to_id": "spoke", "cost_per_lb": 0.12}],
        "hub_warehouse_id": "hub",
    }
    wh, ln, hub, src = _network_inputs_for_cuopt_tri_modal(
        request_wh,
        [],
        "seed_only",
        parallel,
        {"status": "complete", "options": []},
    )
    assert src == "multi_dc_parallel_scenario"
    assert [w["id"] for w in wh] == ["hub", "spoke"]
    assert hub == "hub"
    assert len(ln) == 1
    assert ln[0]["from_id"] == "hub"


def test_cuopt_network_falls_back_to_wno_multi_dc_when_parallel_skipped():
    request_wh = [{"id": "only", "postal": "07055"}]
    parallel = {"status": "skipped", "reason": "placement_mock_rate_grids_incomplete"}
    wno = {
        "status": "complete",
        "options": [
            {
                "option_key": "multi_dc",
                "selected_warehouses": [
                    {"id": "w1", "postal": "07055"},
                    {"id": "w2", "postal": "90012"},
                ],
                "lanes": [{"from_id": "w1", "to_id": "w2", "cost_per_lb": 0.2}],
                "hub_warehouse_id": "w1",
            },
        ],
    }
    wh, ln, hub, src = _network_inputs_for_cuopt_tri_modal(
        request_wh,
        [],
        "only",
        parallel,
        wno,
    )
    assert src == "warehouse_network_recommendation_multi_dc"
    assert {w["id"] for w in wh} == {"w1", "w2"}
    assert hub == "w1"
    assert len(ln) == 1


def test_cuopt_network_request_payload_when_no_recommendation():
    wh_in = [
        {"id": "a", "postal": "10001"},
        {"id": "b", "postal": "20001"},
    ]
    lanes_in = [{"from_id": "a", "to_id": "b", "cost_per_lb": 0.1}]
    wh, ln, hub, src = _network_inputs_for_cuopt_tri_modal(
        wh_in,
        lanes_in,
        "a",
        {"status": "skipped"},
        {"status": "complete", "options": []},
    )
    assert src == "request_payload"
    assert [w["id"] for w in wh] == ["a", "b"]
    assert hub == "a"
    assert ln[0]["from_id"] == "a"

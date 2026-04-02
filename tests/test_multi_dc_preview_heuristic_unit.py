from unie_cortex.services.multi_dc_preview_heuristic import build_multi_dc_preview_body_heuristic


def test_build_multi_dc_preview_body_heuristic_aggregates_zips():
    ol = [
        {"ship_to_postal": "10001"},
        {"ship_to_postal": "10001"},
        {"ship_to_postal": "90210"},
    ]
    body = build_multi_dc_preview_body_heuristic(
        order_lines=ol,
        primary_warehouse={"id": "dc1", "lat": 40.0, "lon": -74.0},
    )
    assert len(body["warehouses"]) == 1
    assert body["warehouses"][0]["id"] == "dc1"
    assert len(body["lanes"]) == 2
    ids = {L["to_id"] for L in body["lanes"]}
    assert "dest_10001" in ids
    assert "dest_90210" in ids

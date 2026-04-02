from unie_cortex.network.us_state_demand_share import label_rollup_hot_state_attachment


def test_hot_attachment_empty_rollup():
    assert label_rollup_hot_state_attachment({"status": "skipped"}) == {}


def test_hot_attachment_includes_tiers():
    att = label_rollup_hot_state_attachment(
        {
            "status": "complete",
            "zip3_count": 3,
            "tiers": {"hot_zip3": ["070"], "medium_zip3": ["100"], "cold_zip3": ["900"]},
            "by_state": {"NJ": {"lines": 10, "pct_of_lines": 50.0}, "CA": {"lines": 10, "pct_of_lines": 50.0}},
        }
    )
    assert att["label_zip3_demand_tiers"]["hot_zip3"] == ["070"]
    assert len(att["label_by_state_top_lines"]) == 2

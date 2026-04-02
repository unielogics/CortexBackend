"""Zone exclusivity for complementary mock DCs."""

from __future__ import annotations

from unie_cortex.network.complementary_zone_exclusion import (
    filter_complement_candidates,
    is_candidate_too_close_to_origin,
    postal_equal,
)


def _six_regional_mock_pool():
    """Fixed pool for zone tests (independent of Prep Center default candidate list)."""
    return [
        {"id": "reg_ne", "postal": "07102"},
        {"id": "reg_se", "postal": "30303"},
        {"id": "reg_mw", "postal": "60607"},
        {"id": "reg_tx", "postal": "77002"},
        {"id": "reg_mt", "postal": "80202"},
        {"id": "reg_wc", "postal": "90012"},
    ]


def test_postal_equal_normalizes():
    assert postal_equal("07208", "07208-1234") is True
    assert postal_equal("07208", "10001") is False


def test_nj_origin_excludes_nearby_regional_mock_dcs():
    origin = "07208"
    pool = _six_regional_mock_pool()
    kept = filter_complement_candidates(origin, pool, carrier="ups", max_easy_zone=3)
    postals = {str(w.get("postal", ""))[:5] for w in kept}
    # Newark-adjacent NE hub should fall in easy mock zone from Elizabeth, NJ
    assert "07102" not in postals
    assert any(p.startswith("9") for p in postals)


def test_is_candidate_too_close_matches_low_mock_zone():
    assert is_candidate_too_close_to_origin("07208", "07102", carrier="ups", max_easy_zone=3) is True

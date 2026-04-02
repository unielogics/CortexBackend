"""Prep Center bundle integration for default warehouse pool and regional freight."""

from pathlib import Path

from unie_cortex.network.facility_freight_mock_defaults import (
    enrich_warehouse_node_dict,
    enrich_warehouse_node_with_regional_fallback,
    regional_archetype_id_for_us_state,
)
from unie_cortex.network.prep_center_loader import load_prep_center_bundle
from unie_cortex.services.smart_warehouse_network import default_us_candidate_warehouses

_ROOT = Path(__file__).resolve().parents[1]
_BUNDLE = _ROOT / "unie_cortex" / "network" / "data" / "prep_center_candidate_warehouses.json"


def test_regional_archetype_id_for_us_state():
    assert regional_archetype_id_for_us_state("TX") == "reg_tx"
    assert regional_archetype_id_for_us_state("CA") == "reg_wc"
    assert regional_archetype_id_for_us_state("MI") == "reg_mw"
    assert regional_archetype_id_for_us_state("NJ") == "reg_ne"
    assert regional_archetype_id_for_us_state("FL") == "reg_se"


def test_enrich_regional_fallback_attaches_freight():
    node = {"id": "wh_custom123", "postal": "78626", "state": "TX"}
    node = enrich_warehouse_node_dict(dict(node))
    node = enrich_warehouse_node_with_regional_fallback(node)
    assert node.get("facility_freight") is not None
    assert "pickup" in node["facility_freight"]


def test_default_pool_uses_bundle_when_present():
    pool = default_us_candidate_warehouses()
    if _BUNDLE.is_file():
        bundle = load_prep_center_bundle()
        assert bundle is not None
        assert len(pool) == len(bundle["candidate_warehouses"])
        assert all(str(w.get("id", "")).startswith("wh_") for w in pool)
        assert all(w.get("facility_freight") for w in pool)
    else:
        assert len(pool) == 6
        assert {w["id"] for w in pool} == {
            "reg_ne",
            "reg_se",
            "reg_mw",
            "reg_tx",
            "reg_mt",
            "reg_wc",
        }

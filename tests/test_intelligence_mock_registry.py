"""Intelligence mock registry shape for /v1/network/intelligence-mock-registry."""

from __future__ import annotations

from unie_cortex.config import settings
from unie_cortex.network.tms_fleet_mocks import list_mock_tractors
from unie_cortex.network.zones import list_supported_carriers
from unie_cortex.services.intelligence_mock_registry import build_intelligence_mock_registry


def _keys_in_cost_fields(rows: list, *required_substrings: str) -> bool:
    for r in rows:
        cfs = r.get("cost_fields") or []
        keys = {str(c.get("key") or "") for c in cfs}
        blob = " ".join(keys)
        for sub in required_substrings:
            if sub not in blob:
                return False
    return True


def test_intelligence_mock_registry_structure():
    reg = build_intelligence_mock_registry(settings)
    assert reg["schema_version"] == "intelligence_mock_registry_v1"
    assert "economics_defaults" in reg
    eco = reg["economics_defaults"]
    assert isinstance(eco.get("cost_fields"), list)
    assert len(eco["cost_fields"]) >= 6
    keys = {c["key"] for c in eco["cost_fields"]}
    assert "economics_default_inbound_receiving_per_unit_usd" in keys
    assert "network_consolidated_linehaul_cost_multiplier" in keys

    whs = reg["warehouses"]
    assert len(whs) >= 1
    assert all("cost_fields" in w and len(w["cost_fields"]) > 0 for w in whs)
    sources = {w["source"] for w in whs}
    assert "audit_baseline" in sources

    carriers = reg["parcel_carriers"]
    assert len(carriers) == len(list_supported_carriers())
    for c in carriers:
        cfs = c["cost_fields"]
        keys_c = {x["key"] for x in cfs}
        assert any("base_usd" in k for k in keys_c)
        assert any("per_lb_usd" in k for k in keys_c)
        assert any("per_zone_usd" in k for k in keys_c)

    brokers = reg["freight_brokers"]
    assert len(brokers) >= 3
    assert _keys_in_cost_fields(brokers, "ltl_mock.min_charge_usd", "ltl_mock.per_lb_usd")

    fleet = reg["linehaul_fleet"]
    assert len(fleet) == len(list_mock_tractors())
    assert all("tractor_id" in row for row in fleet)
    assert all("linehaul_dollar_model" in " ".join(c.get("key", "") for c in row.get("cost_fields", [])) for row in fleet)

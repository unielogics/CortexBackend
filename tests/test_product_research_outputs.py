"""Four triggerable product_research_economics outputs."""

from __future__ import annotations

import copy

import pytest
from fastapi.testclient import TestClient

from unie_cortex.main import app

from unie_cortex.services.product_research_economics import (
    build_product_research_economics,
    normalize_product_research_outputs,
)


def test_normalize_defaults_and_dedupes():
    assert normalize_product_research_outputs(None) == ["original", "ours"]
    assert normalize_product_research_outputs([]) == ["original", "ours"]
    assert normalize_product_research_outputs(
        ["ours", "original", "ours"]
    ) == ["ours", "original"]


def test_normalize_rejects_unknown():
    with pytest.raises(ValueError, match="Invalid product_research_outputs"):
        normalize_product_research_outputs(["ours", "nope"])


def _minimal_tri_modal() -> dict:
    return {
        "schema_version": "item_intelligence_multi_dc_tri_modal_v1",
        "original_input": {"warehouses": [], "lanes": [], "hub_warehouse_id": None},
        "baseline_without_nvidia": {"source": "internal", "status": "ok"},
        "nvidia_enhanced": {"status": "skipped", "source": "disabled"},
        "eligibility": {},
    }


def test_build_four_outputs_fingerprint_and_isolation():
    alloc = {"lines": [{"sku": "S1", "units": 10}]}
    econ = {"per_sku": [{"sku": "S1"}]}
    fnc = {"per_sku": [{"sku": "S1"}]}
    syn = {"run_summary_bullets": ["x"]}
    dem = {"S1": {"monthly_units_est_mid": 5}}
    tri = _minimal_tri_modal()

    block = build_product_research_economics(
        tenant_id="t1",
        operational_warehouse_id="w1",
        request_echo={"warehouses": [{"id": "w1"}]},
        catalog=[{"sku": "S1", "asin": "B00TEST"}],
        demand_by_sku=dem,
        placement_mock_rate_grids={"status": "complete"},
        placement_allocation_share_source="request",
        allocation=alloc,
        landed_cost_economics=econ,
        fulfillment_network_comparison=fnc,
        item_intelligence_synthesis=syn,
        multi_dc_placement_tri_modal=tri,
        requested_outputs=[
            "original",
            "ours",
            "ours_plus_nvidia_enhancements",
            "nvidia_only",
        ],
    )

    assert block["schema_version"] == "product_research_economics_v1"
    outs = block["outputs"]
    assert outs["original"] is not None
    assert outs["ours"] is not None
    assert outs["ours_plus_nvidia_enhancements"] is not None
    assert outs["nvidia_only"] is not None

    assert outs["ours"]["allocation"] == alloc
    assert "optimization_enrichment" not in outs["ours"]
    assert outs["ours_plus_nvidia_enhancements"]["optimization_enrichment"]["baseline_without_nvidia"] == {
        "source": "internal",
        "status": "ok",
    }
    nv = outs["nvidia_only"]
    assert nv["references_outputs_ours"] is True
    assert nv["fingerprint_of_ours"].startswith("sha256:")
    assert nv["optimization_enrichment"]["does_not_replace_outputs_ours"] is True
    assert nv["nvidia_parallel_narrative"]["purpose"] == "comparison_ui_only"
    assert nv["nvidia_enhancement_parts"]["optimization_enrichment"] is not None

    # ours_plus must not alias ours (deep copy)
    assert outs["ours_plus_nvidia_enhancements"]["allocation"] == outs["ours"]["allocation"]
    assert outs["ours_plus_nvidia_enhancements"]["allocation"] is not outs["ours"]["allocation"]

    ours_again = build_product_research_economics(
        tenant_id="t1",
        operational_warehouse_id="w1",
        request_echo={"warehouses": [{"id": "w1"}]},
        catalog=[{"sku": "S1", "asin": "B00TEST"}],
        demand_by_sku=dem,
        placement_mock_rate_grids={"status": "complete"},
        placement_allocation_share_source="request",
        allocation=copy.deepcopy(alloc),
        landed_cost_economics=copy.deepcopy(econ),
        fulfillment_network_comparison=copy.deepcopy(fnc),
        item_intelligence_synthesis=copy.deepcopy(syn),
        multi_dc_placement_tri_modal=None,
        requested_outputs=["ours", "nvidia_only"],
    )
    assert ours_again["outputs"]["ours"] is not None
    assert ours_again["outputs"]["original"] is None
    skipped = ours_again["outputs"]["nvidia_only"]["optimization_enrichment"]
    assert skipped["status"] == "skipped"


def test_api_rejects_invalid_product_research_outputs():
    with TestClient(app) as c:
        r = c.post(
            "/v1/operational/t/w/item-intelligence/run",
            json={
                "warehouses": [{"id": "w", "target_share_pct": 100.0}],
                "lanes": [],
                "include_product_research_economics": True,
                "product_research_outputs": ["invalid_key"],
            },
        )
        assert r.status_code == 422

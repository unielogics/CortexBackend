"""ASIN package hints from Keepa / SP-API payloads and CSV row merge."""

import pytest

from unie_cortex.services.asin_package_enrichment import (
    merge_package_hints_into_canonical_row,
    package_hints_from_keepa_product,
    package_hints_from_spapi_catalog_payload,
)


def test_keepa_package_dimensions_centihundredths_inches():
    h = package_hints_from_keepa_product(
        {
            "packageLength": 1200,
            "packageWidth": 800,
            "packageHeight": 400,
            "packageWeight": 1600,
        }
    )
    assert h["package_length_in"] == 12.0
    assert h["package_width_in"] == 8.0
    assert h["package_height_in"] == 4.0
    assert h["package_weight_lb"] == pytest.approx(1.0, rel=0, abs=0.02)


def test_spapi_item_package_attributes():
    body = {
        "attributes": {
            "item_package_weight": [{"value": 2.5, "unit": "pounds"}],
            "item_package_dimensions": [
                {
                    "length": {"value": 10.0, "unit": "inches"},
                    "width": {"value": 8.0, "unit": "inches"},
                    "height": {"value": 4.0, "unit": "inches"},
                }
            ],
        }
    }
    h = package_hints_from_spapi_catalog_payload(body)
    assert h["package_weight_lb"] == 2.5
    assert h["package_length_in"] == 10.0
    assert h["package_width_in"] == 8.0
    assert h["package_height_in"] == 4.0


def test_merge_only_fills_missing():
    c = {"package_weight_lb": 1.0, "quantity": 2.0}
    hints = {
        "package_weight_lb": 9.0,
        "package_length_in": 11.0,
        "enrichment_source": "keepa_product",
    }
    meta = merge_package_hints_into_canonical_row(c, hints)
    assert c["package_weight_lb"] == 1.0
    assert c["package_length_in"] == 11.0
    assert meta["filled_fields"] == ["package_length_in"]

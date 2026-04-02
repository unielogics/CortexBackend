import json
from pathlib import Path

from unie_cortex.spine.fixture_warehouse_baseline import (
    AUDIT_BASELINE_ORIGIN_ZIP5,
    AUDIT_BASELINE_WAREHOUSE_ID,
    baseline_candidate_warehouses,
)

_ROOT = Path(__file__).resolve().parents[1]
_BUNDLE = _ROOT / "unie_cortex" / "network" / "data" / "prep_center_candidate_warehouses.json"


def test_baseline_matches_prep_center_bundle_or_elizabeth_fallback():
    wh = baseline_candidate_warehouses()
    assert len(wh) == 1
    if _BUNDLE.is_file():
        bundle = json.loads(_BUNDLE.read_text(encoding="utf-8"))
        bid = bundle.get("baseline_warehouse_id")
        candidates = bundle.get("candidate_warehouses") or []
        expected = next((c for c in candidates if c.get("id") == bid), None)
        if not expected and candidates:
            expected = candidates[0]
        assert expected is not None
        assert wh[0]["postal"] == expected["postal"]
        assert wh[0]["id"] == expected["id"]
        assert wh[0].get("label") == expected.get("label")
        assert AUDIT_BASELINE_ORIGIN_ZIP5 == expected["postal"]
        assert AUDIT_BASELINE_WAREHOUSE_ID == expected["id"]
    else:
        assert AUDIT_BASELINE_ORIGIN_ZIP5 == "07208"
        assert wh[0]["postal"] == "07208"
        assert "Elizabeth" in (wh[0].get("label") or "")

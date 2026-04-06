from unie_cortex.services.nim_csv_mapping import merge_mappings, redact_sample_rows, validate_and_filter_mapping
from unie_cortex.spine.ingest import CANONICAL_LABEL
import asyncio

from unie_cortex.config import settings
from unie_cortex.services.nim_csv_mapping import infer_csv_mapping_with_nim


def test_redact_sample_rows_truncates_and_email():
    rows = [{"email_col": "a@b.co", "x": "y" * 80}]
    out = redact_sample_rows(rows, max_len=20)
    assert "[redacted_email]" in out[0]["email_col"]
    assert str(out[0]["x"]).endswith("...")


def test_validate_mapping_drops_bad_canonical():
    m, w = validate_and_filter_mapping(
        {"A": "label_amount_usd", "B": "not_a_field"},
        allowed=set(CANONICAL_LABEL),
        headers={"A", "B"},
    )
    assert m == {"A": "label_amount_usd"}
    assert any("invalid_canonical" in x for x in w)


def test_merge_preserves_deterministic_on_conflict():
    allowed = set(CANONICAL_LABEL)
    headers = {"Track", "Amt"}
    det = {"Track": "tracking_number", "Amt": "label_amount_usd"}
    nim = {"Track": "carrier", "Amt": "weight_lb"}
    merged, _ = merge_mappings(det, nim, allowed=allowed, headers=headers)
    assert merged["Track"] == "tracking_number"
    assert merged["Amt"] == "label_amount_usd"


def test_infer_mapping_enriches_quality_narration_for_seller_mode():
    async def _run():
        return await infer_csv_mapping_with_nim(
            settings,
            kind="order_financials",
            headers=["OrderID", "Revenue", "Mystery Charge"],
            sample_rows=[{"OrderID": "A-1", "Revenue": "10.5", "Mystery Charge": "1.2"}],
            templates=[],
            wms_hint=None,
        )

    out = asyncio.run(_run())
    payload = out.model_dump()
    assert payload["mode"] == "seller_optimization"
    q = payload.get("mapping_quality") or {}
    assert q.get("mode") == "seller_optimization"
    assert q.get("mapped_headers", 0) >= 2
    assert isinstance(payload.get("narration"), list) and payload["narration"]
    assert isinstance(payload.get("recommended_actions"), list) and payload["recommended_actions"]

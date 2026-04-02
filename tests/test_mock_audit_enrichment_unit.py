from unie_cortex.spine.mock_audit_enrichment import inject_fbm_pick_pack_billing_rows


def test_inject_adds_rows_and_preserves_header():
    raw = b"InvoiceId,LineId,FeeCode,ServiceStart,ServiceEnd,AmountUsd,Currency\nINV-1,BL1,WH_RENT,2024-01-01,2024-01-31,100,USD\n"
    out = inject_fbm_pick_pack_billing_rows(raw, 3)
    text = out.decode("utf-8")
    assert text.count("\n") >= 5  # header + 1 + 3
    assert "FBM_PICK_PACK" in text
    assert "INV-MOCK-HANDLE" in text

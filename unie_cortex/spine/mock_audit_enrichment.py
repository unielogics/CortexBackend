"""Optional enrichment of mock audit CSV bytes for demos (realistic per-order billing handles)."""

from __future__ import annotations

import csv
import io
from typing import Any


def inject_fbm_pick_pack_billing_rows(raw: bytes, count: int, *, seed: int = 42) -> bytes:
    """
    Append synthetic FBM_PICK_PACK lines (~$2.50–$3.50) so variable_ops billing math behaves like real 3PL handles.

    Expects standard audit billing header: InvoiceId,LineId,FeeCode,ServiceStart,ServiceEnd,AmountUsd,Currency
    """
    if count <= 0:
        return raw
    text = raw.decode("utf-8-sig", errors="replace")
    buf = io.StringIO()
    reader = csv.DictReader(io.StringIO(text))
    fieldnames = reader.fieldnames
    if not fieldnames:
        return raw
    rows = list(reader)
    # Deterministic pseudo-random amounts in [2.50, 3.49]
    rng = seed
    for i in range(count):
        rng = (rng * 1103515245 + 12345) & 0x7FFFFFFF
        cents = 250 + (rng % 100)
        amt = f"{cents / 100:.2f}"
        rows.append(
            {
                "InvoiceId": f"INV-MOCK-HANDLE-{i+1:04d}",
                "LineId": f"H{i+1}",
                "FeeCode": "FBM_PICK_PACK",
                "ServiceStart": "2024-06-15",
                "ServiceEnd": "2024-06-15",
                "AmountUsd": amt,
                "Currency": "USD",
            }
        )
    w = io.StringIO()
    writer = csv.DictWriter(w, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for r in rows:
        writer.writerow({k: r.get(k, "") for k in fieldnames})
    return w.getvalue().encode("utf-8")


def summarize_mock_pipeline_checks(wh_intel: dict[str, Any], outcome_dump: dict[str, Any]) -> dict[str, Any]:
    """Compact dict for logging / assertions."""
    fe = wh_intel.get("fulfillment_economics") if isinstance(wh_intel.get("fulfillment_economics"), dict) else {}
    hr = outcome_dump.get("human_readable") if isinstance(outcome_dump.get("human_readable"), dict) else {}
    return {
        "warehouse_intelligence_schema": wh_intel.get("schema_version"),
        "variable_ops_usd": (wh_intel.get("billing_components_usd") or {}).get("variable_ops_usd"),
        "fixed_like_usd": (wh_intel.get("billing_components_usd") or {}).get("fixed_like_usd"),
        "estimated_cost_per_fulfillment_usd": wh_intel.get("estimated_cost_per_fulfillment_usd"),
        "naive_implausible": fe.get("naive_per_event_implausible_vs_reference"),
        "strategy_suggestion_count": len(wh_intel.get("strategy_suggestions") or []),
        "human_headline_present": bool(hr.get("headline")),
        "human_strategy_cards": len(hr.get("warehouse_strategy_suggestions") or []),
    }

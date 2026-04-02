"""
User-facing vocabulary for network scenarios and CSV planning.

- **multi_warehouse**: Parcel from the best recommended DC per destination (legacy internal key: ``direct``).
- **single_warehouse**: Inbound linehaul into one receive DC, then parcel to customers (legacy: ``consolidated``).

CSV baseline channel (how you sell today) is separate from ``fulfillment_mode`` on the scenario engine.
"""

from __future__ import annotations

from typing import Any, Literal

CsvBaselineFulfillment = Literal["fba", "fbw", "fbm"]

CSV_BASELINE_COMPARISON_TITLE: dict[str, str] = {
    "fba": "Current (FBA)",
    "fbw": "Current (FBW)",
    "fbm": "Current (FBM)",
}

NETWORK_PATH_LABELS = {
    "multi_warehouse": (
        "Multi-warehouse: ship from the cheapest recommended DC per destination bucket "
        "(parcel-only from origins; no modeled inbound linehaul between your DCs)."
    ),
    "single_warehouse": (
        "Single-warehouse: modeled inbound linehaul to one receive DC, then parcel to destinations "
        "(final mile priced from the receive node, not the original origin)."
    ),
}


def normalize_csv_baseline_fulfillment(raw: str | None) -> CsvBaselineFulfillment:
    """Default FBA when unset or unknown (Amazon-heavy exports)."""
    if not raw:
        return "fba"
    x = str(raw).strip().lower()
    if x in ("fba", "fbw", "fbm"):
        return x  # type: ignore[return-value]
    return "fba"


def csv_baseline_comparison_title(channel: str | None) -> str:
    ch = normalize_csv_baseline_fulfillment(channel)
    return CSV_BASELINE_COMPARISON_TITLE[ch]


def build_network_fulfillment_economics(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Per-unit fulfill costs and savings % for multi_warehouse vs single_warehouse (after vocabulary aliases exist).

    ``savings_pct_multi_warehouse_vs_single_warehouse`` = ``100 * (single - multi) / single`` on all-in $/unit —
    positive when multi is cheaper vs the single-warehouse baseline.
    """
    if payload.get("status") != "complete":
        return {
            "status": str(payload.get("status") or "incomplete"),
            "note": "scenario not complete; fulfillment economics not computed",
        }
    econ = payload.get("economics_per_unit_at_qty")
    if not isinstance(econ, dict):
        return {"status": "partial", "note": "missing economics_per_unit_at_qty"}

    mw = payload.get("multi_warehouse") or payload.get("direct") or {}
    sw = payload.get("single_warehouse") or payload.get("consolidated") or {}

    mw_pu = econ.get("multi_warehouse_all_in_usd_per_unit")
    if mw_pu is None:
        mw_pu = econ.get("direct_all_in_usd_per_unit")
    sw_pu = econ.get("single_warehouse_all_in_usd_per_unit")
    if sw_pu is None:
        sw_pu = econ.get("consolidated_all_in_usd_per_unit")

    mw_tr = econ.get("multi_warehouse_transport_only_usd_per_unit")
    if mw_tr is None:
        mw_tr = econ.get("direct_transport_parcel_only_usd_per_unit")
    sw_tr = econ.get("single_warehouse_transport_only_usd_per_unit")
    if sw_tr is None:
        sw_tr = econ.get("consolidated_transport_only_usd_per_unit")

    mw_tot = mw.get("total_usd") if isinstance(mw, dict) else None
    sw_tot = sw.get("total_usd") if isinstance(sw, dict) else None

    def _savings_pct(single: Any, multi: Any) -> float | None:
        if single is None or multi is None:
            return None
        try:
            sf, mf = float(single), float(multi)
        except (TypeError, ValueError):
            return None
        if sf <= 0:
            return None
        return round((sf - mf) / sf * 100.0, 4)

    savings_usd: float | None = None
    if mw_tot is not None and sw_tot is not None:
        try:
            savings_usd = round(float(sw_tot) - float(mw_tot), 2)
        except (TypeError, ValueError):
            savings_usd = None

    return {
        "status": "complete",
        "assumptions_version": payload.get("assumptions_version"),
        "qty": payload.get("qty"),
        "multi_warehouse_fulfillment_cost_usd_per_unit": mw_pu,
        "single_warehouse_fulfillment_cost_usd_per_unit": sw_pu,
        "multi_warehouse_transport_only_usd_per_unit": mw_tr,
        "single_warehouse_transport_only_usd_per_unit": sw_tr,
        "multi_warehouse_fulfillment_total_usd": mw_tot,
        "single_warehouse_fulfillment_total_usd": sw_tot,
        "savings_pct_multi_warehouse_vs_single_warehouse": _savings_pct(sw_pu, mw_pu),
        "savings_pct_multi_warehouse_vs_single_warehouse_from_totals": _savings_pct(sw_tot, mw_tot),
        "savings_usd_if_choose_multi_instead_of_single": savings_usd,
        "savings_pct_note": (
            "100 * (single_warehouse - multi_warehouse) / single_warehouse on all-in fulfillment $/unit. "
            "Positive => multi is cheaper; negative => multi costs more."
        ),
    }


def enrich_scenario_result_vocabulary(payload: dict[str, Any]) -> None:
    """
    Mutates a compare-v2 / integrated scenario dict: adds ``multi_warehouse`` / ``single_warehouse``
    aliases and a ``vocabulary`` block. Legacy keys ``direct`` / ``consolidated`` remain for compatibility.
    """
    if payload.get("status") != "complete":
        return
    if "direct" in payload and "multi_warehouse" not in payload:
        payload["multi_warehouse"] = payload["direct"]
    if "consolidated" in payload and "single_warehouse" not in payload:
        payload["single_warehouse"] = payload["consolidated"]

    if "delta_usd" in payload and "delta_multi_warehouse_minus_single_warehouse_usd" not in payload:
        payload["delta_multi_warehouse_minus_single_warehouse_usd"] = payload["delta_usd"]

    e = payload.get("economics_per_unit_at_qty")
    if isinstance(e, dict):
        if "direct_all_in_usd_per_unit" in e:
            e.setdefault("multi_warehouse_all_in_usd_per_unit", e["direct_all_in_usd_per_unit"])
        if "consolidated_all_in_usd_per_unit" in e:
            e.setdefault("single_warehouse_all_in_usd_per_unit", e["consolidated_all_in_usd_per_unit"])
        if "direct_transport_parcel_only_usd_per_unit" in e:
            e.setdefault(
                "multi_warehouse_transport_only_usd_per_unit",
                e["direct_transport_parcel_only_usd_per_unit"],
            )
        if "consolidated_transport_only_usd_per_unit" in e:
            e.setdefault(
                "single_warehouse_transport_only_usd_per_unit",
                e["consolidated_transport_only_usd_per_unit"],
            )

    fbm = payload.get("fbm_full_financial_breakdown")
    if isinstance(fbm, dict):
        if "direct" in fbm and "multi_warehouse" not in fbm:
            fbm["multi_warehouse"] = fbm["direct"]
        if "consolidated" in fbm and "single_warehouse" not in fbm:
            fbm["single_warehouse"] = fbm["consolidated"]
        if "delta_direct_all_in_minus_consolidated_all_in_usd" in fbm:
            fbm.setdefault(
                "delta_multi_warehouse_all_in_minus_single_warehouse_all_in_usd",
                fbm["delta_direct_all_in_minus_consolidated_all_in_usd"],
            )

    rec = str(payload.get("recommendation") or "")
    if rec == "linehaul_then_parcel":
        rnp = "single_warehouse"
    elif rec == "noop":
        delta = float(payload.get("delta_usd") or 0)
        rnp = "multi_warehouse" if delta < 0 else "no_change"
    else:
        rnp = "no_change"

    payload["vocabulary"] = {
        "csv_baseline_fulfillment": None,
        "csv_baseline_comparison_title": None,
        "network_paths": {
            "multi_warehouse": {
                "public_label": "Multi-warehouse",
                "description": NETWORK_PATH_LABELS["multi_warehouse"],
                "legacy_response_key": "direct",
            },
            "single_warehouse": {
                "public_label": "Single-warehouse",
                "description": NETWORK_PATH_LABELS["single_warehouse"],
                "legacy_response_key": "consolidated",
            },
        },
        "recommended_network_path": rnp,
        "recommendation_codes_note": (
            "recommendation linehaul_then_parcel means prefer single-warehouse path; "
            "noop means no change vs threshold — see recommended_network_path and delta_multi_warehouse_minus_single_warehouse_usd."
        ),
    }

    payload["network_fulfillment_economics"] = build_network_fulfillment_economics(payload)

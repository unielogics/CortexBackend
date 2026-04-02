"""Backbone completeness: required feeds for competitive + profitability warehouse audit."""

from __future__ import annotations

from typing import Any

from unie_cortex.services.audit_contracts import AuditGrainReport

BACKBONE_FEEDS = (
    "order_lines",
    "asn",
    "billing",
    "employees",
    "order_financials",
)


def _feed_row_count(grain: AuditGrainReport, name: str) -> int:
    m = {
        "order_lines": grain.order_lines.row_count,
        "asn": grain.asn.row_count,
        "billing": grain.billing.row_count,
        "employees": grain.employees.row_count,
        "order_financials": grain.order_financials.row_count,
    }
    return int(m.get(name, 0))


def build_backbone_completeness(
    *,
    grain: AuditGrainReport,
    facility_profile: dict[str, Any] | None,
    network_context: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    Backbone = order_lines, asn, billing, employees, order_financials + facility + primary postal.
    Supplemental (not scored here): labels, tasks.
    """
    fp = dict(facility_profile) if isinstance(facility_profile, dict) else {}
    nc = network_context if isinstance(network_context, dict) else {}

    feeds: dict[str, Any] = {}
    missing: list[str] = []
    present_n = 0

    for name in BACKBONE_FEEDS:
        n = _feed_row_count(grain, name)
        ok = n > 0
        if ok:
            present_n += 1
        else:
            missing.append(name)
        feeds[name] = {"row_count": n, "present": ok}

    # Facility: sqft and (headcount in profile OR employee rows)
    sqft_ok = fp.get("sqft") not in (None, "", 0)
    hc_prof = fp.get("headcount_reported")
    try:
        hc_ok = hc_prof is not None and int(hc_prof) > 0
    except (TypeError, ValueError):
        hc_ok = False
    emp_rows = grain.employees.row_count > 0
    headcount_ok = hc_ok or emp_rows
    facility_ok = bool(sqft_ok and headcount_ok)
    feeds["facility"] = {
        "present": facility_ok,
        "sqft_present": bool(sqft_ok),
        "headcount_signal_present": bool(headcount_ok),
        "headcount_from_profile": hc_ok,
        "employee_rows": grain.employees.row_count,
    }
    if not sqft_ok:
        missing.append("facility.sqft")
    if not headcount_ok:
        missing.append("facility.headcount_or_employees")

    # Primary ship-from postal
    postal_ok = False
    whs = nc.get("candidate_warehouses")
    if isinstance(whs, list):
        for w in whs:
            if isinstance(w, dict) and (w.get("postal") or "").strip():
                postal_ok = True
                break
    feeds["primary_ship_from_postal"] = {"present": postal_ok}
    if not postal_ok:
        missing.append("network_context.candidate_warehouses[].postal")

    total_checks = len(BACKBONE_FEEDS) + 2  # facility bundle + postal
    score = (present_n + (1 if facility_ok else 0) + (1 if postal_ok else 0)) / total_checks
    score = round(min(1.0, max(0.0, score)), 4)

    if score >= 0.85 and not missing:
        confidence = "high"
    elif score >= 0.5:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "schema_version": "audit_backbone_v1",
        "feeds": feeds,
        "missing": missing,
        "backbone_score": score,
        "report_confidence": confidence,
        "note": "Backbone feeds anchor 3PL + seller economics; labels/tasks are supplemental.",
    }


# Map backbone ``missing`` keys to upload opportunity ``category`` values for sort boosting.
_MISSING_TO_UPLOAD_CATEGORIES: dict[str, frozenset[str]] = {
    "order_lines": frozenset({"orders", "tasks"}),
    "asn": frozenset({"inbound", "tasks"}),
    "billing": frozenset({"billing"}),
    "employees": frozenset({"facility"}),
    "order_financials": frozenset({"order_financials"}),
    "facility.sqft": frozenset({"facility"}),
    "facility.headcount_or_employees": frozenset({"facility"}),
    "network_context.candidate_warehouses[].postal": frozenset({"network"}),
}


def sort_upload_opportunities_by_backbone(
    opportunities: list[dict[str, Any]],
    missing: list[str] | None,
) -> list[dict[str, Any]]:
    """Within the same priority tier, surface items that close backbone gaps first."""
    if not opportunities:
        return opportunities
    miss = missing or ()
    boosted: frozenset[str] = frozenset()
    for m in miss:
        boosted |= _MISSING_TO_UPLOAD_CATEGORIES.get(m, frozenset())

    priority_rank = {"high": 0, "medium": 1, "low": 2}

    def sort_key(idx_item: tuple[int, dict[str, Any]]) -> tuple[int, int, int]:
        idx, it = idx_item
        pr = priority_rank.get(it.get("priority"), 9)
        cat = str(it.get("category") or "")
        # 0 = addresses a backbone gap, 1 = supplemental only
        gap_rank = 0 if (not boosted or cat in boosted) else 1
        return (pr, gap_rank, idx)

    indexed = list(enumerate(opportunities))
    indexed.sort(key=sort_key)
    return [it for _, it in indexed]

"""Actionable 'improve uploads' items: what to add so opportunity analysis gets sharper."""

from __future__ import annotations

from typing import Any

from unie_cortex.services.audit_contracts import AuditGrainReport


def _add(
    out: list[dict[str, Any]],
    *,
    priority: str,
    category: str,
    title: str,
    detail: str,
    unlocks: list[str],
) -> None:
    out.append(
        {
            "priority": priority,
            "category": category,
            "title": title,
            "detail": detail,
            "unlocks": unlocks,
        }
    )


def build_data_upload_opportunities(
    *,
    grain: AuditGrainReport,
    facility_profile: dict[str, Any] | None,
    spine_coverage: dict[str, Any] | None,
    warehouse_intelligence: dict[str, Any] | None,
    network_context: dict[str, Any] | None = None,
    label_delta_usd: float | None,
    label_ratio: float | None,
    label_ratio_warn: float | None,
    money_opp_low: float | None,
) -> list[dict[str, Any]]:
    """
    Deterministic checklist: richer uploads → better warehouse economics and opportunity surfacing.
    Not a judgment of the operator — a product contract for what each feed enables.
    """
    fp = dict(facility_profile) if isinstance(facility_profile, dict) else {}
    wi = warehouse_intelligence if isinstance(warehouse_intelligence, dict) else {}
    cov = spine_coverage if isinstance(spine_coverage, dict) else {}
    nc = network_context if isinstance(network_context, dict) else {}

    out: list[dict[str, Any]] = []

    postal_ok = False
    for w in nc.get("candidate_warehouses") or []:
        if isinstance(w, dict) and str(w.get("postal") or "").strip():
            postal_ok = True
            break
    if not postal_ok and (grain.order_lines.row_count > 0 or grain.labels.row_count > 0):
        _add(
            out,
            priority="high",
            category="network",
            title="Set primary ship-from postal on network_context.candidate_warehouses",
            detail="Origin ZIP anchors parcel benchmarks, rate-shop grids, and network competitiveness narratives.",
            unlocks=["Label cost benchmark vs zone", "Multi-DC preview origin node", "Backbone postal completeness"],
        )

    if grain.order_lines.row_count == 0 and (grain.billing.row_count > 0 or grain.asn.row_count > 0):
        _add(
            out,
            priority="high",
            category="orders",
            title="Upload order_lines (shipped outbound)",
            detail="Backbone competitive audit needs shipped order lines for channel mix, destinations, and billing denominators.",
            unlocks=["orders_per_month_estimate", "destination spread / multi-DC hooks", "Fulfillment economics denominator"],
        )
    t = grain.tasks.row_count
    syn = grain.synthetic_task_count

    if t > 0 and syn == t:
        _add(
            out,
            priority="high",
            category="tasks",
            title="Replace or supplement synthetic tasks with WMS export",
            detail="All task rows are synthesized from ASN/order timestamps — good for coverage, weak for labor truth.",
            unlocks=[
                "True picks/hour and zone heatmaps",
                "Credible utilization vs headcount baseline",
                "Shift-level efficiency before/after optimization",
            ],
        )
    elif t == 0 and (grain.asn.row_count > 0 or grain.order_lines.row_count > 0):
        _add(
            out,
            priority="high",
            category="tasks",
            title="Upload tasks or ensure ASN + order_lines for synthesis",
            detail="No task facts yet; throughput module stays thin until WMS tasks exist or synthesis runs.",
            unlocks=["Throughput findings", "Zone concentration themes"],
        )

    if grain.billing.row_count == 0:
        _add(
            out,
            priority="high",
            category="billing",
            title="Upload billing / invoice line CSV",
            detail="Without billed amounts, cost-per-fulfillment and 3PL margin story stay unanchored to accounting.",
            unlocks=[
                "estimated_cost_per_fulfillment_usd",
                "Fee-code mix vs activity (next: allocation rules)",
            ],
        )
    elif grain.billing.row_count > 0:
        fe = wi.get("fulfillment_economics") if isinstance(wi.get("fulfillment_economics"), dict) else {}
        if fe.get("naive_per_event_implausible_vs_reference"):
            _add(
                out,
                priority="high",
                category="billing",
                title="Split invoice lines: fixed rent/labor vs FBM handle vs FBA prep",
                detail=(
                    "Total billing ÷ shipment lines inflates “per order” cost versus a typical low single-digit dollar handle. "
                    "Use fee_code (or GL mapping) to isolate per-order pick/pack from period and prep charges."
                ),
                unlocks=[
                    "variable_ops_per_fulfillment_event_usd",
                    "billing_components_usd (fixed vs variable)",
                ],
            )
        elif wi.get("estimated_cost_per_fulfillment_usd") is None:
            _add(
                out,
                priority="medium",
                category="billing",
                title="Fix billing amount mapping or fulfillment denominator",
                detail="Billing rows exist but trusted variable handle could not be computed — check amount_usd, fee_code, and shipped order lines or labels.",
                unlocks=["Cost per fulfillment", "Billing vs rate-card variance (planned)"],
            )

    if fp.get("sqft") in (None, "", 0):
        _add(
            out,
            priority="medium",
            category="facility",
            title="Set facility sqft in network-context facility_profile",
            detail="Square footage is used to scale utilization narratives and future storage economics.",
            unlocks=["Storage / throughput density context", "Dock-to-stock heuristics"],
        )
    if fp.get("headcount_reported") in (None, "", 0) and grain.employees.row_count == 0:
        _add(
            out,
            priority="medium",
            category="facility",
            title="Provide headcount_reported or employee roster",
            detail="Capacity baseline (tasks/hour anchor) needs FTE signal from profile or employees CSV.",
            unlocks=["Headcount-based throughput baseline", "Observed vs baseline % when tasks are dense in time"],
        )

    if grain.asn.row_count == 0:
        _add(
            out,
            priority="medium",
            category="inbound",
            title="Upload ASN / inbound receipt lines",
            detail="Inbound volume and timing are inferred only from outbound + labels today.",
            unlocks=["Receive labor alignment", "Dock scheduling context", "Synthetic receive tasks grounded in receipts"],
        )

    ol_keys = grain.order_lines.join_keys_present or {}
    if grain.order_lines.row_count > 0 and not ol_keys.get("shipped_at_iso"):
        _add(
            out,
            priority="high",
            category="orders",
            title="Map and populate shipped_at on order lines",
            detail="Ship timestamps drive synthetic ship tasks and fulfillment event counts.",
            unlocks=["Outbound event timing", "Fulfillment denominator aligned to ship activity"],
        )

    lb = grain.labels.join_keys_present or {}
    if grain.labels.row_count > 0 and not lb.get("sku"):
        _add(
            out,
            priority="medium",
            category="labels",
            title="Improve label SKU fill rate",
            detail="Low SKU presence weakens joins from labels to orders and item intelligence.",
            unlocks=["label ↔ order_line ↔ financial reconciliation"],
        )

    if grain.order_financials.row_count == 0:
        _add(
            out,
            priority="high" if grain.order_lines.row_count > 0 else "medium",
            category="order_financials",
            title="Upload order_financials (backbone seller economics)",
            detail=(
                "Seller-side revenue, fees, and margin are backbone inputs alongside 3PL billing — "
                "they anchor profitability vs competitiveness, not only optional planning runs."
            ),
            unlocks=["Seller net margin vs 3PL handle", "Planning-run scenarios", "Order economics themes"],
        )

    for mod_key, mod in cov.items():
        if not isinstance(mod, dict):
            continue
        st = mod.get("status")
        if st not in ("complete", None) and mod.get("missing"):
            _add(
                out,
                priority="medium",
                category="mapping",
                title=f"Complete column mapping for {mod_key}",
                detail=f"Missing: {mod.get('missing')}",
                unlocks=[f"Enable {mod_key} in spine coverage"],
            )

    if (
        label_delta_usd is not None
        and label_delta_usd > 0
        and (money_opp_low is None or money_opp_low <= 0)
        and label_ratio is not None
        and label_ratio_warn is not None
        and label_ratio < label_ratio_warn
    ):
        _add(
            out,
            priority="low",
            category="labels",
            title="Label spend above benchmark but tier still 'in_band'",
            detail=(
                f"Ratio actual/benchmark is {label_ratio:.3f} (warn at {label_ratio_warn}). "
                "Dollar band may still show savings — tune audit_benchmark profile or treat as operational signal."
            ),
            unlocks=["Stronger 'opportunity' tier when ratio crosses threshold", "Explicit pass-through label audit vs carrier invoice"],
        )

    for note in wi.get("synthetic_fill") or []:
        if isinstance(note, str) and note.strip():
            _add(
                out,
                priority="low",
                category="data_quality",
                title="Warehouse intelligence gap",
                detail=note.strip(),
                unlocks=["Clearer cost and utilization metrics"],
            )

    priority_rank = {"high": 0, "medium": 1, "low": 2}
    out.sort(key=lambda x: priority_rank.get(x.get("priority"), 9))
    return out


def themes_from_upload_opportunities(items: list[dict[str, Any]], max_themes: int = 5) -> list[str]:
    """Short lines for audit outcome themes."""
    lines: list[str] = []
    for it in items[:max_themes]:
        p = it.get("priority", "")
        title = it.get("title") or ""
        if not title:
            continue
        prefix = "Upload gap: " if p == "high" else "Data: "
        lines.append(f"{prefix}{title}.")
    return lines

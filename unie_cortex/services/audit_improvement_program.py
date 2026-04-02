"""Consolidate audit signals into a single improvement presentation (efficiency, billing, optimization, data)."""

from __future__ import annotations

from typing import Any

from unie_cortex.services.audit_contracts import AuditGrainReport


def build_improvement_program(
    *,
    grain: AuditGrainReport,
    warehouse_intelligence: dict[str, Any] | None,
    competitive_kpis: dict[str, Any] | None,
    upload_opportunities: list[dict[str, Any]],
    backbone_completeness: dict[str, Any] | None,
    label_cost: dict[str, Any],
    throughput: dict[str, Any],
) -> dict[str, Any]:
    """
    Deterministic roll-up for customer-facing “what to improve” — no new ML.
    Axes: labor_efficiency, billing_margin, fulfillment_optimization, data_enrichment.
    """
    wi = warehouse_intelligence if isinstance(warehouse_intelligence, dict) else {}
    kp = competitive_kpis if isinstance(competitive_kpis, dict) else {}
    bb = backbone_completeness if isinstance(backbone_completeness, dict) else {}
    lc = label_cost if isinstance(label_cost, dict) else {}
    tp = throughput if isinstance(throughput, dict) else {}

    fe = wi.get("fulfillment_economics") if isinstance(wi.get("fulfillment_economics"), dict) else {}
    cap = wi.get("capacity_baseline") if isinstance(wi.get("capacity_baseline"), dict) else {}
    lnx = wi.get("label_network_insights") if isinstance(wi.get("label_network_insights"), dict) else {}
    cna = wi.get("complementary_network_audit") if isinstance(wi.get("complementary_network_audit"), dict) else {}
    asm = wi.get("audit_sharpness_metrics") if isinstance(wi.get("audit_sharpness_metrics"), dict) else {}
    ore = asm.get("overall_readiness") if isinstance(asm.get("overall_readiness"), dict) else {}

    items: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(
        key: str,
        *,
        axis: str,
        priority: str,
        headline: str,
        detail: str,
        evidence_paths: list[str],
    ) -> None:
        if key in seen:
            return
        seen.add(key)
        items.append(
            {
                "id": key,
                "axis": axis,
                "priority": priority,
                "headline": headline,
                "detail": detail,
                "evidence_paths": evidence_paths,
            }
        )

    tier = str(ore.get("tier") or "")
    if tier in ("low", "medium"):
        sc = ore.get("score_0_1")
        add(
            "data_readiness_sharpness",
            axis="data_enrichment",
            priority="high" if tier == "low" else "medium",
            headline="Fill-rate readiness is not high — caveat dollar and labor claims",
            detail=(
                f"Overall readiness tier={tier} (score {sc}). "
                "Many WMS exports omit columns; map what you have and add fee_code, ship-from, and real task timestamps when possible. "
                "See audit_sharpness_metrics.feed_coverage for per-feed key_fill_rates."
            ),
            evidence_paths=["warehouse_intelligence.audit_sharpness_metrics"],
        )

    if fe.get("naive_per_event_implausible_vs_reference"):
        naive = fe.get("naive_total_billing_per_fulfillment_event_usd")
        ref = fe.get("reference_typical_order_handle_usd") or 3.0
        add(
            "billing_naive_total_misleading",
            axis="billing_margin",
            priority="high",
            headline="Billing math is blending fixed and variable charges",
            detail=(
                f"Total invoice dollars ÷ shipment lines (~${float(naive):,.2f}/line in this extract) is not a fair per-order "
                f"fulfillment fee next to a ~${float(ref):.2f} pick/pack reference. Split fee_code / GL into fixed period, prep, and variable ops."
            ),
            evidence_paths=["warehouse_intelligence.fulfillment_economics", "competitive_kpis.naive_total_per_line_usd"],
        )

    fixed_share = kp.get("billing_fixed_share_of_total_pct")
    if isinstance(fixed_share, (int, float)) and fixed_share >= 55:
        pr = "high" if fixed_share >= 65 else "medium"
        add(
            "billing_fixed_share_high",
            axis="billing_margin",
            priority=pr,
            headline="Fixed warehouse charges dominate the invoice",
            detail=(
                f"About {fixed_share:.1f}% of billed USD is classified as fixed-like (rent, blocks, etc.). "
                "Benchmark variable fulfillment using variable_ops ÷ shipped activity, not total ÷ lines."
            ),
            evidence_paths=["competitive_kpis.billing_fixed_share_of_total_pct", "warehouse_intelligence.billing_components_usd"],
        )

    h2r = kp.get("handle_to_reference_typical_ratio")
    if isinstance(h2r, (int, float)) and h2r >= 1.35:
        add(
            "billing_variable_handle_elevated",
            axis="billing_margin",
            priority="medium",
            headline="Variable per-shipment handle looks high vs reference",
            detail=(
                f"Estimated variable handle vs ~${kp.get('reference_typical_handle_usd') or 3:.2f} reference is about {h2r:.2f}× — "
                "validate FBA prep vs FBM lines before treating as pure 3PL margin pressure."
            ),
            evidence_paths=["competitive_kpis.handle_to_reference_typical_ratio", "warehouse_intelligence.estimated_cost_per_fulfillment_usd"],
        )

    if lc.get("status") == "complete":
        try:
            du = float(lc.get("delta_usd") or 0)
        except (TypeError, ValueError):
            du = 0.0
        if du > 0:
            add(
                "optimization_label_spend_vs_benchmark",
                axis="fulfillment_optimization",
                priority="high",
                headline="Parcel label spend is above the reference benchmark",
                detail=(
                    f"Aggregate label charges are about ${_fmt(du)} above benchmark in this window — rate-shop per origin, "
                    "review carrier/service mix, and reconcile accessorials."
                ),
                evidence_paths=["spine_summary.label_cost_delta_usd", "warehouse_intelligence.label_network_insights"],
            )

    ut = cap.get("observed_vs_baseline_throughput_pct")
    if isinstance(ut, (int, float)):
        if ut < 72:
            add(
                "labor_throughput_below_baseline_anchor",
                axis="labor_efficiency",
                priority="medium",
                headline="Observed task throughput sits below the headcount baseline anchor",
                detail=(
                    f"Rough observed vs baseline throughput is about {ut:.0f}% — use as a pre-optimization anchor "
                    "(slotting, batching, shift design). Upload dense WMS tasks if this used synthetic timestamps."
                ),
                evidence_paths=["warehouse_intelligence.capacity_baseline"],
            )
        elif ut > 130:
            add(
                "labor_throughput_above_baseline_stress",
                axis="labor_efficiency",
                priority="medium",
                headline="Observed throughput is well above the planning baseline",
                detail=(
                    f"Observed vs baseline is about {ut:.0f}% — check whether the window, synthetic tasks, or surge volume skew the read; "
                    "still useful for staffing and peak planning conversations."
                ),
                evidence_paths=["warehouse_intelligence.capacity_baseline"],
            )

    opf = kp.get("orders_per_fte_month_estimate")
    if isinstance(opf, (int, float)) and opf > 0 and opf < 450 and (kp.get("headcount_used") or 0) > 0:
        add(
            "labor_orders_per_fte_low",
            axis="labor_efficiency",
            priority="low",
            headline="Orders-per-FTE/month looks modest vs high-volume benchmarks",
            detail=(
                f"Rough read ~{opf:.0f} orders/FTE/month from shipped dates and headcount — directional only; "
                "real picks/hour needs WMS task export."
            ),
            evidence_paths=["competitive_kpis.orders_per_fte_month_estimate", "competitive_kpis.headcount_used"],
        )

    if grain.tasks.row_count > 0 and grain.synthetic_task_count >= grain.tasks.row_count:
        add(
            "labor_synthetic_tasks_caveat",
            axis="data_enrichment",
            priority="medium",
            headline="Labor signals are inferred, not from your WMS task export",
            detail="All task rows in this run are synthetic from ASN/order lines — efficiency gaps are directional until you upload real pick/put tasks with timestamps.",
            evidence_paths=["data_quality.grain.synthetic_task_count", "data_quality.grain.tasks"],
        )

    bz = tp.get("bottleneck_zones_top5") if isinstance(tp.get("bottleneck_zones_top5"), list) else []
    if bz and isinstance(bz[0], dict) and bz[0].get("zone") is not None:
        z = bz[0].get("zone")
        add(
            "labor_zone_concentration",
            axis="labor_efficiency",
            priority="medium",
            headline=f"Pick/put workload concentrates in zone {z}",
            detail="High zone concentration often points to slotting, batch cart design, or labor balance — pair with slotting review.",
            evidence_paths=["spine_artifact.throughput.bottleneck_zones_top5"],
        )

    if cna.get("status") == "complete":
        try:
            d_cna = float(cna.get("aggregate_delta_usd_per_line_out_of_region") or 0)
        except (TypeError, ValueError):
            d_cna = 0.0
        if d_cna > 0:
            add(
                "optimization_multinode_parcel_mock",
                axis="fulfillment_optimization",
                priority="medium",
                headline="National demand may benefit from a second ship-from (planning mock)",
                detail=(
                    f"On sampled out-of-region ZIP3s, cheapest-origin proxy averages ~${_fmt(d_cna)} less per line than forcing the primary hub — "
                    "confirm with live quotes, inventory, and service policy; see complementary_network_audit."
                ),
                evidence_paths=["warehouse_intelligence.complementary_network_audit"],
            )
        else:
            add(
                "optimization_multinode_explore",
                axis="fulfillment_optimization",
                priority="low",
                headline="Multi-node parcel audit ran — review lanes even if mock delta is flat",
                detail="Mock zones and capped destinations may hide savings; use hot-zip-grid per candidate warehouse for deeper work.",
                evidence_paths=["warehouse_intelligence.complementary_network_audit"],
            )

    if lnx.get("multi_location_opportunity") and not any(
        x.get("id") in ("optimization_multinode_parcel_mock", "optimization_multinode_explore") for x in items
    ):
        add(
            "optimization_label_network_multiorigin",
            axis="fulfillment_optimization",
            priority="medium",
            headline="Parcel economics support multi-origin rate shopping",
            detail="Labels + network_context support comparing ship-from ZIPs (hot-zip-grid, scenario compare) — not only carrier negotiation at one building.",
            evidence_paths=["warehouse_intelligence.label_network_insights"],
        )

    miss = bb.get("missing") if isinstance(bb.get("missing"), list) else []
    for i, m in enumerate(miss[:4]):
        if not isinstance(m, str) or not m.strip():
            continue
        mk = f"data_backbone:{m[:48]}"
        if mk in seen:
            continue
        seen.add(mk)
        items.append(
            {
                "id": mk,
                "axis": "data_enrichment",
                "priority": "high" if i == 0 else "medium",
                "headline": "Close a backbone data gap",
                "detail": m.strip(),
                "evidence_paths": ["backbone_completeness.missing"],
            }
        )

    for u in upload_opportunities:
        if not isinstance(u, dict):
            continue
        if str(u.get("priority") or "").lower() != "high":
            continue
        title = (u.get("title") or "").strip()
        if not title:
            continue
        uid = f"data_upload:{title[:60]}"
        if uid in seen:
            continue
        seen.add(uid)
        unl = u.get("unlocks") or []
        unlock_txt = (" Unlocks: " + "; ".join(str(x) for x in unl[:3]) + ".") if unl else ""
        items.append(
            {
                "id": uid,
                "axis": "data_enrichment",
                "priority": "high",
                "headline": title,
                "detail": ((u.get("detail") or "")[:400] + unlock_txt).strip(),
                "evidence_paths": ["data_quality.upload_opportunities"],
            }
        )
        if sum(1 for x in items if str(x.get("id", "")).startswith("data_upload:")) >= 5:
            break

    order = {"high": 0, "medium": 1, "low": 2}
    items.sort(key=lambda x: (order.get(str(x.get("priority")), 9), x.get("axis") or ""))

    counts: dict[str, int] = {}
    for it in items:
        ax = str(it.get("axis") or "other")
        counts[ax] = counts.get(ax, 0) + 1

    intro = (
        f"This run surfaces {len(items)} improvement threads across "
        f"labor/efficiency ({counts.get('labor_efficiency', 0)}), billing/margin ({counts.get('billing_margin', 0)}), "
        f"fulfillment optimization ({counts.get('fulfillment_optimization', 0)}), and data enrichment ({counts.get('data_enrichment', 0)}). "
        "Prioritize highs with ops and finance; enrich feeds to tighten confidence."
    )

    return {
        "schema_version": "improvement_program_v1",
        "intro": intro,
        "counts_by_axis": counts,
        "items": items[:24],
    }


def _fmt(n: float) -> str:
    s = f"{n:,.2f}"
    if s.endswith(".00"):
        s = s[:-3]
    return s

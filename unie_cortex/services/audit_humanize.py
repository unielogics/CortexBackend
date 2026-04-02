"""Plain-language summaries for audit outcomes (API + UI)."""

from __future__ import annotations

from typing import Any

from unie_cortex.services.audit_contracts import AuditGrainReport, AuditOpportunityBlock


def _fmt_money(n: float | None) -> str | None:
    if n is None:
        return None
    try:
        x = float(n)
    except (TypeError, ValueError):
        return None
    sign = "-" if x < 0 else ""
    x = abs(x)
    s = f"{x:,.2f}"
    if s.endswith(".00"):
        s = s[:-3]
    return f"{sign}${s}"


def _fmt_count(n: int) -> str:
    return f"{n:,}"


def _tier_plain(tier: str | None) -> str:
    if tier == "opportunity":
        return (
            "Compared to our reference rates, parcel label spend looks higher than typical — "
            "worth validating with fresh quotes and carrier mix."
        )
    if tier == "in_band":
        return "Parcel label spend looks broadly in line with our reference band — you can still fine-tune carriers and service levels."
    return "We don't have enough labeled shipping charges yet to score spend against a reference."


def _finding_human(f: dict[str, Any]) -> dict[str, str] | None:
    t = (f.get("type") or "").strip()
    msg = (f.get("message") or "").strip()
    sev = (f.get("severity") or "").strip()
    if t == "label_spend_above_benchmark":
        return {
            "title": "Label spend vs benchmark",
            "detail": msg or "Total label charges are above the heuristic benchmark — rate shopping may reduce pass-through cost.",
        }
    if t == "zone_concentration":
        z = f.get("zone")
        return {
            "title": "Work concentrated in one zone",
            "detail": f"A lot of pick/put activity shows up in zone {z}. That often points to slotting or labor balance opportunities."
            if z is not None
            else (msg or "Task volume is concentrated in one zone."),
        }
    if t == "sku_velocity_signal":
        return {
            "title": "Fast-moving SKUs",
            "detail": msg or "A few SKUs dominate label or task signals — useful for slotting and inventory placement.",
        }
    if msg:
        return {"title": t.replace("_", " ").title() or "Finding", "detail": msg}
    return None


def build_human_readable_audit(
    *,
    grain: AuditGrainReport,
    opportunity: AuditOpportunityBlock,
    warehouse_intelligence: dict[str, Any] | None,
    themes: list[str],
    upload_opportunities: list[dict[str, Any]],
    spine_findings: list[dict[str, Any]],
    label_cost: dict[str, Any],
    throughput: dict[str, Any],
    improvement_program: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Deterministic copy — no LLM. Safe for dashboards and email snippets."""

    t1 = {
        "asn": grain.asn.row_count,
        "order_lines": grain.order_lines.row_count,
        "billing": grain.billing.row_count,
        "employees": grain.employees.row_count,
        "synthetic_tasks": grain.synthetic_task_count,
        "uploaded_tasks": grain.tasks.row_count - grain.synthetic_task_count,
    }
    wi = warehouse_intelligence if isinstance(warehouse_intelligence, dict) else {}
    fe = (wi.get("fulfillment_estimate") or {}) if isinstance(wi.get("fulfillment_estimate"), dict) else {}
    fecon = wi.get("fulfillment_economics") if isinstance(wi.get("fulfillment_economics"), dict) else {}
    loc_ctx = wi.get("location_context") if isinstance(wi.get("location_context"), dict) else {}
    vol_bl = wi.get("volume_baseline") if isinstance(wi.get("volume_baseline"), dict) else {}
    lab_bl = wi.get("labor_baseline") if isinstance(wi.get("labor_baseline"), dict) else {}
    events = fe.get("fulfillment_events_estimate")
    try:
        events_i = int(events) if events is not None else None
    except (TypeError, ValueError):
        events_i = None

    cpf = wi.get("estimated_cost_per_fulfillment_usd")
    try:
        cpf_f = float(cpf) if cpf is not None else None
    except (TypeError, ValueError):
        cpf_f = None

    bill_total = wi.get("billing_usd_total")
    try:
        bill_f = float(bill_total) if bill_total is not None else None
    except (TypeError, ValueError):
        bill_f = None

    lc_status = (label_cost or {}).get("status")
    lc_rows = label_cost.get("row_count")
    delta = label_cost.get("delta_usd")

    high_upload = sum(1 for u in upload_opportunities if u.get("priority") == "high")

    # Headline
    if high_upload >= 2:
        headline = "We connected your warehouse files, but a couple of data upgrades would make the story much sharper."
    elif high_upload == 1:
        headline = "Analysis is running; one priority upload would unlock stronger labor and cost signals."
    elif lc_status == "complete" and (delta or 0) > 0:
        headline = "Your parcel labels look more expensive than our reference — there may be savings in rates and carriers."
    elif cpf_f is not None and cpf_f > 0:
        headline = "Billing and activity are speaking to each other — see the rough cost-per-shipment read below."
    else:
        headline = "Here is a plain-English read of what we could learn from the files you shared."

    summary_lines: list[str] = []
    parts: list[str] = []
    if t1["asn"]:
        parts.append(f"{_fmt_count(t1['asn'])} inbound (ASN) lines")
    if t1["order_lines"]:
        parts.append(f"{_fmt_count(t1['order_lines'])} order lines")
    if t1["billing"]:
        parts.append(f"{_fmt_count(t1['billing'])} billing lines")
    if parts:
        summary_lines.append("In the warehouse feeds: " + ", ".join(parts) + ".")

    ip = improvement_program if isinstance(improvement_program, dict) else {}
    if ip.get("intro"):
        summary_lines.append(str(ip["intro"]))

    asm_sharp = wi.get("audit_sharpness_metrics") if isinstance(wi.get("audit_sharpness_metrics"), dict) else {}
    or_sharp = asm_sharp.get("overall_readiness") if isinstance(asm_sharp.get("overall_readiness"), dict) else {}
    if or_sharp.get("tier") is not None:
        summary_lines.append(
            f"Data sharpness: overall readiness **{or_sharp.get('tier')}** (score {or_sharp.get('score_0_1')}) from real column fill-rates — "
            "sparse WMS/billing files still flow through; see warehouse_intelligence.audit_sharpness_metrics for gaps."
        )

    if grain.synthetic_task_count and grain.tasks.row_count:
        if grain.synthetic_task_count == grain.tasks.row_count:
            summary_lines.append(
                "Labor-style tasks were inferred from receipts and orders — not from your WMS — "
                "so throughput and utilization are directional, not ground truth."
            )
        elif grain.synthetic_task_count > 0:
            summary_lines.append(
                f"Some tasks ({_fmt_count(grain.synthetic_task_count)}) were synthesized to fill gaps; "
                "uploaded tasks are included where present."
            )

    if lc_status == "skipped":
        summary_lines.append("We did not analyze parcel label spend yet — upload mapped label charges when you have them.")
    elif lc_status == "complete" and lc_rows is not None:
        try:
            n_lab = int(lc_rows)
        except (TypeError, ValueError):
            n_lab = 0
        if n_lab > 0:
            d = _fmt_money(float(delta)) if delta is not None else None
            summary_lines.append(
                f"Across {_fmt_count(n_lab)} label rows, spend vs our reference benchmark"
                + (f" shows about {d} difference" if d else " is summarized in the numbers below")
                + "."
            )

    lns = wi.get("label_network_insights") if isinstance(wi.get("label_network_insights"), dict) else {}
    if lns.get("multi_location_opportunity") and grain.labels.row_count > 0:
        n_o = int(lns.get("distinct_origin_postals_on_labels") or 0)
        cand_n = len(lns.get("network_candidate_ship_from_postals") or [])
        summary_lines.append(
            f"Parcel network: {n_o} origin ZIP(s) on labels and {cand_n} candidate ship-from(s) in network_context — "
            "rate-shop **per origin** (hot-zip-grid) and, if destinations are broad, evaluate a second ship-from with scenario compare or multi-DC preview."
        )

    cna = wi.get("complementary_network_audit") if isinstance(wi.get("complementary_network_audit"), dict) else {}
    if cna.get("status") == "complete":
        dpl = cna.get("aggregate_delta_usd_per_line_out_of_region")
        sh = cna.get("out_of_region_order_share_pct_all_zip3")
        try:
            dpl_f = float(dpl) if dpl is not None else None
        except (TypeError, ValueError):
            dpl_f = None
        seg = (
            f"Complementary-network mock: {cna.get('tiered_total_nodes')} node plan from volume tiering; "
            f"~{sh}% of merged lines are out-of-region vs primary mock zones."
            if sh is not None
            else f"Complementary-network mock: {cna.get('tiered_total_nodes')} node plan from volume tiering."
        )
        if dpl_f is not None and dpl_f > 0:
            seg += f" Sampled out-of-region lanes average ~{_fmt_money(dpl_f)} less per line if you rate-shop to the best mock origin vs forcing the hub — not a contractual savings claim."
        elif dpl_f is not None:
            seg += " Sampled lanes did not show positive mock savings vs single hub; still validate nationally with live quotes."
        summary_lines.append(seg + " See complementary_network_audit.limitations.")

    if tp := (throughput or {}).get("status"):
        if tp == "complete":
            summary_lines.append("Throughput patterns from tasks are available — check zone concentration in findings.")
        elif tp == "skipped":
            summary_lines.append("Throughput stayed light — usually because task timestamps or zones are missing.")

    synthetic_notes = wi.get("synthetic_fill") if isinstance(wi.get("synthetic_fill"), list) else []
    for note in synthetic_notes[:2]:
        if isinstance(note, str) and note.strip():
            summary_lines.append(note.strip())

    for warn in (fecon.get("interpretation_warnings") or [])[:2]:
        if isinstance(warn, str) and warn.strip():
            summary_lines.append(warn.strip())

    if isinstance(fecon.get("interpretation_summary"), str) and fecon["interpretation_summary"].strip():
        summary_lines.append(fecon["interpretation_summary"].strip())

    at_a_glance: list[dict[str, str]] = []
    at_a_glance.append(
        {
            "title": "Data volume",
            "body": f"ASN {_fmt_count(t1['asn'])}, order lines {_fmt_count(t1['order_lines'])}, "
            f"billing lines {_fmt_count(t1['billing'])}, roster rows {_fmt_count(t1['employees'])}.",
        }
    )
    if events_i is not None:
        at_a_glance.append(
            {
                "title": "Fulfillment events (estimate)",
                "body": f"We used about {_fmt_count(events_i)} shipment-related events as the divisor for billing math "
                "(labels or shipped lines, whichever is larger).",
            }
        )
    if cpf_f is not None and cpf_f > 0:
        at_a_glance.append(
            {
                "title": "Variable ops per shipped line (best read)",
                "body": f"About {_fmt_money(cpf_f)} per line using variable pick/pack-style fee codes only — closer to a per-order handle than total invoice ÷ lines.",
            }
        )
    elif bill_f is not None and bill_f > 0:
        at_a_glance.append(
            {
                "title": "Billed amount in file",
                "body": f"About {_fmt_money(bill_f)} in billing lines; we could not pair it to a fulfillment count yet.",
            }
        )

    if fecon.get("naive_total_billing_per_fulfillment_event_usd") is not None:
        nn = float(fecon["naive_total_billing_per_fulfillment_event_usd"])
        ref = float(fecon.get("reference_typical_order_handle_usd") or 3.0)
        at_a_glance.append(
            {
                "title": "Naive total ÷ lines (often misleading)",
                "body": f"~{_fmt_money(nn)} per shipped line if you divide all billing by lines — typically inflated vs a ~{_fmt_money(ref)} pick/pack reference when rent, prep, and labor blocks are on the same invoice.",
            }
        )

    postal = loc_ctx.get("primary_ship_from_postal")
    wh_lbl = loc_ctx.get("primary_warehouse_label")
    sqft = loc_ctx.get("sqft")
    if postal or sqft or wh_lbl:
        loc_parts = []
        if wh_lbl:
            loc_parts.append(str(wh_lbl))
        if postal:
            loc_parts.append(f"ship-from ZIP {postal}")
        if sqft:
            loc_parts.append(f"~{_fmt_count(int(sqft))} sq ft")
        at_a_glance.append({"title": "Facility & origin", "body": "; ".join(loc_parts) + "."})

    opm = vol_bl.get("orders_per_month_estimate")
    if opm is not None:
        try:
            opm_f = float(opm)
            at_a_glance.append(
                {
                    "title": "Order volume (from shipped timestamps)",
                    "body": f"About {opm_f:,.1f} distinct orders per month in the sample window "
                    f"({vol_bl.get('distinct_orders_in_window')} orders over ~{vol_bl.get('months_in_window_fractional', 0)} mo). "
                    "Use with headcount for a coarse productivity anchor.",
                }
            )
        except (TypeError, ValueError):
            pass

    avgh = lab_bl.get("avg_hourly_rate_usd")
    if avgh is not None:
        im = lab_bl.get("implied_monthly_labor_usd_order_of_magnitude")
        body = f"Average mapped hourly rate about {_fmt_money(float(avgh))}/hr from roster rows."
        if im is not None:
            body += f" Rough monthly payroll magnitude (order-of-magnitude): ~{_fmt_money(float(im))}."
        at_a_glance.append({"title": "Labor snapshot", "body": body})

    cap = wi.get("capacity_baseline") if isinstance(wi.get("capacity_baseline"), dict) else {}
    bline = cap.get("baseline_tasks_per_hour_from_headcount")
    obs_pct = cap.get("observed_vs_baseline_throughput_pct")
    if isinstance(bline, (int, float)) and bline > 0:
        body = f"Using your headcount hint, a planning anchor is on the order of {_fmt_count(int(round(bline)))} task-equivalents per hour (industry-style assumption)."
        if isinstance(obs_pct, (int, float)):
            body += f" Observed activity vs that anchor: about {obs_pct:.0f}%."
        else:
            body += " We did not compute observed vs that anchor (often because task timestamps span too long a calendar range)."
        at_a_glance.append({"title": "Capacity snapshot", "body": body})

    opp_low = opportunity.money_opportunities_usd_low
    opp_high = opportunity.money_opportunities_usd_high
    if isinstance(opp_low, (int, float)) and isinstance(opp_high, (int, float)) and (opp_low > 0 or opp_high > 0):
        at_a_glance.append(
            {
                "title": "Label savings band (model)",
                "body": f"Rough modeled band from the spine: {_fmt_money(float(opp_low))} to {_fmt_money(float(opp_high))} "
                "— illustrative, not a guarantee.",
            }
        )

    lns_ag = wi.get("label_network_insights") if isinstance(wi.get("label_network_insights"), dict) else {}
    if lns_ag.get("multi_location_opportunity") and grain.labels.row_count > 0:
        topd = lns_ag.get("top_destination_zip3_by_label_rows") or []
        top_txt = ", ".join(f"{t.get('zip3')}×{t.get('label_rows')}" for t in topd[:4] if isinstance(t, dict)) or "n/a"
        at_a_glance.append(
            {
                "title": "Multi-location parcel logic",
                "body": f"Top destination ZIP3 bands by label rows: {top_txt}. "
                "Run hot-zip-grid from **each** ship-from postal; add nodes only when zone mix + volume justify inventory split.",
            }
        )

    cna_ag = wi.get("complementary_network_audit") if isinstance(wi.get("complementary_network_audit"), dict) else {}
    if cna_ag.get("status") == "complete":
        topd = cna_ag.get("per_destination_top") or []
        top_txt = ", ".join(
            f"{t.get('dest_zip3')}: Δ${_fmt_money(float(t.get('delta_usd_primary_minus_best') or 0))}"
            for t in topd[:4]
            if isinstance(t, dict)
        ) or "see block"
        at_a_glance.append(
            {
                "title": "Complementary network (mock)",
                "body": f"Tiered mock nodes {cna_ag.get('tiered_total_nodes')}; out-of-region share ~{cna_ag.get('out_of_region_order_share_pct_all_zip3')}%. "
                f"Largest sampled primary−best deltas: {top_txt}. Planning-only — confirm with carrier quotes.",
            }
        )

    if ip.get("intro"):
        cx = ip.get("counts_by_axis") if isinstance(ip.get("counts_by_axis"), dict) else {}
        at_a_glance.append(
            {
                "title": "Improvement program (this run)",
                "body": (
                    f"{len(ip['items'])} threads — labor/efficiency: {cx.get('labor_efficiency', 0)}, "
                    f"billing/margin: {cx.get('billing_margin', 0)}, fulfillment optimization: {cx.get('fulfillment_optimization', 0)}, "
                    f"data enrichment: {cx.get('data_enrichment', 0)}. See improvement_program for headlines and evidence paths."
                ),
            }
        )

    if or_sharp.get("tier") is not None:
        at_a_glance.append(
            {
                "title": "Data readiness & metric sharpness",
                "body": (
                    f"Overall readiness **{or_sharp.get('tier')}** (score {or_sharp.get('score_0_1')}). "
                    "Per-feed key fill rates and partial metrics are in warehouse_intelligence.audit_sharpness_metrics — "
                    "missing WMS columns stay optional; AI should caveat claims when tier is not high."
                ),
            }
        )

    tier_sentence = _tier_plain(opportunity.benchmark_tier)

    money_plain: str | None = None
    if isinstance(opp_low, (int, float)) and isinstance(opp_high, (int, float)) and opp_high > 0:
        money_plain = (
            f"The audit engine suggests a possible label-related opportunity in the "
            f"{_fmt_money(float(opp_low))}–{_fmt_money(float(opp_high))} range for the data you loaded — "
            "confirm with live quotes."
        )

    wh_econ: str | None = None
    ref_h = float(fecon.get("reference_typical_order_handle_usd") or 3.0)
    naive_n = fecon.get("naive_total_billing_per_fulfillment_event_usd")
    if cpf_f is not None and cpf_f > 0 and events_i is not None:
        wh_econ = (
            f"Using variable-style fee lines only, we estimate about {_fmt_money(cpf_f)} per shipped line vs "
            f"~{_fmt_money(ref_h)} as a coarse pick/pack reference. Total billing is about {_fmt_money(bill_f) if bill_f is not None else 'N/A'} "
            f"across {_fmt_count(events_i)} lines — reconcile fee codes to FBA prep vs FBM vs fixed rent with finance."
        )
    elif fecon.get("naive_per_event_implausible_vs_reference") and naive_n is not None and events_i is not None:
        wh_econ = (
            f"Dividing all billing (~{_fmt_money(bill_f) if bill_f is not None else 'N/A'}) by {_fmt_count(events_i)} shipment lines "
            f"implies ~{_fmt_money(float(naive_n))} per line — that is not a realistic per-order fulfillment fee when "
            f"you usually fulfill around ${_fmt_money(ref_h)} for handling alone. Split invoices by service type and map fee_code."
        )
    elif bill_f is not None and bill_f > 0:
        wh_econ = f"We see about {_fmt_money(bill_f)} in billing lines; add shipped order lines or labels so we can divide by activity sensibly."

    what_this_means = (
        "These notes are generated from the CSVs you mapped — they highlight where money and labor show up, "
        "and where missing feeds limit confidence. Use them as a conversation starter with ops and finance, "
        "not as a final savings claim."
    )

    priority_label = {"high": "Soon", "medium": "Next", "low": "When convenient"}
    next_steps: list[str] = []
    for u in upload_opportunities[:5]:
        pl = priority_label.get(str(u.get("priority") or ""), "Note")
        title = u.get("title") or ""
        unlocks = u.get("unlocks") or []
        tail = f" Then you get: {unlocks[0]}." if unlocks else ""
        next_steps.append(f"[{pl}] {title}{tail}")

    findings_human = []
    for f in spine_findings or []:
        if isinstance(f, dict):
            h = _finding_human(f)
            if h:
                findings_human.append(h)

    upload_opps_display: list[dict[str, Any]] = []
    for u in upload_opportunities:
        upload_opps_display.append(
            {
                **u,
                "priority_label": priority_label.get(str(u.get("priority") or ""), u.get("priority")),
                "unlocks_plain": "You could then see: " + "; ".join(u.get("unlocks") or []) if u.get("unlocks") else None,
            }
        )

    strat_out: list[dict[str, Any]] = []
    for s in wi.get("strategy_suggestions") or []:
        if not isinstance(s, dict):
            continue
        strat_out.append(
            {
                "category": s.get("category"),
                "priority": s.get("priority"),
                "title": s.get("title"),
                "detail": (s.get("detail") or "")[:600],
                "actions": s.get("actions") if isinstance(s.get("actions"), list) else [],
            }
        )

    imp_items_out: list[dict[str, Any]] = []
    for it in ip.get("items") or []:
        if not isinstance(it, dict):
            continue
        imp_items_out.append(
            {
                "id": it.get("id"),
                "axis": it.get("axis"),
                "priority": it.get("priority"),
                "headline": it.get("headline"),
                "detail": it.get("detail"),
                "evidence_paths": it.get("evidence_paths") if isinstance(it.get("evidence_paths"), list) else [],
            }
        )

    base: dict[str, Any] = {
        "headline": headline,
        "summary_lines": summary_lines,
        "at_a_glance": at_a_glance,
        "what_this_means": what_this_means,
        "next_steps": next_steps,
        "benchmark_tier_plain": tier_sentence,
        "label_spend_plain": money_plain,
        "warehouse_economics_plain": wh_econ,
        "findings_for_humans": findings_human,
        "upload_opportunities_display": upload_opps_display,
        "warehouse_strategy_suggestions": strat_out[:12],
    }
    if ip.get("schema_version") or ip.get("intro") or imp_items_out:
        base["improvement_program"] = {
            "schema_version": ip.get("schema_version"),
            "intro": ip.get("intro"),
            "counts_by_axis": ip.get("counts_by_axis") if isinstance(ip.get("counts_by_axis"), dict) else {},
            "items": imp_items_out,
        }
    return base

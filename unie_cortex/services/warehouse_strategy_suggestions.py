"""Strategic suggestions for assessment warehouse flows (FBA prep vs FBM, network, rate shop).

Structured like other suggestion scaffolds in the codebase: deterministic, API-friendly list.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from unie_cortex.services.audit_contracts import AuditGrainReport
from unie_cortex.services.warehouse_intelligence_baseline import REFERENCE_TYPICAL_ORDER_HANDLE_USD


def _primary_warehouse(nc: dict[str, Any] | None) -> tuple[str | None, str | None]:
    if not isinstance(nc, dict):
        return None, None
    whs = nc.get("candidate_warehouses")
    if not isinstance(whs, list):
        return None, None
    for w in whs:
        if not isinstance(w, dict):
            continue
        p = w.get("postal")
        if p and str(p).strip():
            return str(p).strip(), (w.get("label") or w.get("id") or w.get("name"))
    return None, None


def _dest_zip_spread(order_lines: list[dict[str, Any]]) -> dict[str, Any]:
    zips = [str(r.get("ship_to_postal") or "").strip()[:5] for r in order_lines if (r.get("ship_to_postal") or "").strip()]
    zips = [z for z in zips if len(z) >= 3]
    if not zips:
        return {"distinct_dest_zips": 0, "regions_rough": 0, "note": "no destination zips"}
    prefixes = {z[:3] for z in zips}
    return {
        "distinct_dest_zips": len(set(zips)),
        "regions_rough": len(prefixes),
        "sample_zips": list(dict.fromkeys(zips))[:8],
    }


def build_warehouse_strategy_suggestions(
    *,
    warehouse_intelligence: dict[str, Any],
    order_lines: list[dict[str, Any]],
    labels: list[dict[str, Any]],
    network_context: dict[str, Any] | None,
    grain: AuditGrainReport,
    competitive_kpis: dict[str, Any] | None = None,
    label_network_insights: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    wi = warehouse_intelligence if isinstance(warehouse_intelligence, dict) else {}
    nc = network_context if isinstance(network_context, dict) else {}
    lns = label_network_insights if isinstance(label_network_insights, dict) else {}
    cna = wi.get("complementary_network_audit") if isinstance(wi.get("complementary_network_audit"), dict) else {}
    postal, wh_label = _primary_warehouse(nc)
    spread = _dest_zip_spread(order_lines)

    fe = wi.get("fulfillment_economics") or {}
    warn = (fe.get("interpretation_warnings") or []) if isinstance(fe, dict) else []
    naive_high = bool(fe.get("naive_per_event_implausible_vs_reference")) if isinstance(fe, dict) else False

    if naive_high or any("invoice" in w.lower() or "rent" in w.lower() or "fixed" in w.lower() for w in warn):
        out.append(
            {
                "category": "billing_and_services",
                "priority": "high",
                "title": "Split FBA prep, FBM fulfillment, and fixed warehouse charges in billing",
                "detail": (
                    "3PL invoices usually blend period rent, labor blocks, prep (FBA), and per-order FBM handles. "
                    "Dividing total invoice dollars by outbound order count will look wildly inflated versus a ~$3 "
                    "typical pick/pack handle. Map fee_code (or GL) into fixed vs variable buckets, or upload "
                    "per-order fee lines for FBM only."
                ),
                "actions": [
                    "Tag billing lines as fixed_period | variable_ops | prep_service",
                    "Compare variable_ops total ÷ shipped orders to your quoted per-order handle",
                ],
            }
        )

    if grain.labels.row_count > 0 and lns.get("multi_location_opportunity"):
        parts: list[str] = []
        dv = lns.get("spine_label_cost_delta_usd")
        if dv is not None:
            try:
                parts.append(f"Benchmark vs actual shows ~${float(dv):,.2f} aggregate gap on labels in this extract.")
            except (TypeError, ValueError):
                pass
        low, high = lns.get("spine_label_savings_band_low_usd"), lns.get("spine_label_savings_band_high_usd")
        if low is not None and high is not None:
            try:
                parts.append(
                    f"Heuristic recoverable band about ${float(low):,.2f}–${float(high):,.2f} if quotes move toward reference."
                )
            except (TypeError, ValueError):
                pass
        norig = int(lns.get("distinct_origin_postals_on_labels") or 0)
        cand = lns.get("network_candidate_ship_from_postals") if isinstance(lns.get("network_candidate_ship_from_postals"), list) else []
        miss_pct = lns.get("pct_rows_missing_origin_postal")
        loc = (
            f"Labels show {norig} distinct origin ZIP(s); network_context lists {len(cand)} candidate ship-from postal(s). "
        )
        try:
            if miss_pct is not None and float(miss_pct) > 5:
                loc += f"{float(miss_pct):.1f}% of label rows lack origin_postal — map it so spend rolls up to the correct building. "
        except (TypeError, ValueError):
            pass
        tail = (
            "Run parcel **rate-shop / hot-zip-grid per ship-from ZIP** (each candidate warehouse and each origin on labels). "
            "If geography is broad, pair that with **multi-origin scenario compare** or **multi-dc-preview** so inventory placement "
            "and zone mix both move — not carrier negotiation alone."
        )
        out.append(
            {
                "category": "parcel_multi_origin",
                "priority": "high",
                "title": "Capture label savings: per-origin rate shop + optional multi-node ship-from",
                "detail": (" ".join(parts) + " " + loc + tail).strip(),
                "actions": [
                    "POST /v1/network/rate-shop/hot-zip-grid — repeat per candidate_warehouses[].postal and per distinct label origin_postal.",
                    "POST /v1/network/scenarios/compare-v2 (or compare-v2-integrated) — evaluate adding a second ship-from vs cheaper single-origin mix.",
                    "Map labels.origin_postal on every row; reconcile to WMS ship nodes.",
                ],
            }
        )

    if cna.get("status") == "complete":
        delta = cna.get("aggregate_delta_usd_per_line_out_of_region")
        share = cna.get("out_of_region_order_share_pct_all_zip3")
        ncomp = len(cna.get("selected_complement_nodes") or [])
        try:
            d_f = float(delta) if delta is not None else 0.0
        except (TypeError, ValueError):
            d_f = 0.0
        detail_parts = [
            f"Mock audit used primary {cna.get('primary_origin_postal')} plus {ncomp} complementary node(s) "
            f"(tier cap {cna.get('tiered_total_nodes')}), excluding same/easy mock zones per {cna.get('exclusion_rules_applied', {}).get('zone_carrier_mock', 'ups')} rules."
        ]
        if share is not None:
            detail_parts.append(f"~{share}% of merged label/order lines fall in out-of-region ZIP3s by mock zone.")
        if d_f > 0:
            detail_parts.append(
                f"On sampled out-of-region demand, cheapest-origin proxy averages ~${d_f:.2f}/line less than forcing all volume from the primary — confirm with live quotes and inventory policy."
            )
        else:
            detail_parts.append(
                "Sampled lanes did not show a positive mock savings vs single hub; still validate with live quotes if destinations are national."
            )
        out.append(
            {
                "category": "parcel_complementary_network",
                "priority": "medium" if d_f > 0 else "low",
                "title": "Multi-node parcel proxy vs single hub (planning mock)",
                "detail": " ".join(detail_parts),
                "actions": [
                    "Read warehouse_intelligence.complementary_network_audit for methodology and limitations.",
                    "POST /v1/network/rate-shop/hot-zip-grid for deeper per-cell work; use AUDIT_COMPLEMENTARY_NETWORK_ENABLED=false if audit latency is an issue.",
                ],
            }
        )

    channels = Counter((str(r.get("channel") or "").strip().upper() or "UNKNOWN") for r in order_lines)
    if len(order_lines) > 20 and len([k for k in channels if k != "UNKNOWN"]) >= 2:
        top = ", ".join(f"{k}:{v}" for k, v in channels.most_common(4))
        out.append(
            {
                "category": "service_mix",
                "priority": "medium",
                "title": "Model FBA prep separately from FBM outbound",
                "detail": (
                    f"Order-line channel mix in the extract: {top}. Prep work, cartonization, and Amazon inbound "
                    "differ economically from consumer FBM parcels. Report and benchmark each stream."
                ),
                "actions": ["Segment KPIs by channel", "Allocate labor and billing lines to prep vs outbound"],
            }
        )

    if spread.get("distinct_dest_zips", 0) >= 15 and spread.get("regions_rough", 0) >= 8:
        out.append(
            {
                "category": "network",
                "priority": "medium",
                "title": "Evaluate single vs multi-warehouse fulfillment",
                "detail": (
                    f"Many destination ZIPs ({spread.get('distinct_dest_zips')}) across broad regions suggest "
                    "parcel cost and time-in-transit gains from a regional or multi-DC strategy — similar to "
                    "multi-DC placement runs used with catalog/ASIN intelligence. Use POST /v1/assessment/multi-dc-preview "
                    f"with candidate nodes and lanes, and compare to staying on one ship-from ({wh_label or postal or 'primary DC'})."
                ),
                "actions": [
                    "POST /v1/assessment/multi-dc-preview with warehouse lat/lon and lane demand",
                    "POST /v1/network/rate-shop/hot-zip-grid from primary origin postal",
                ],
            }
        )
    elif spread.get("distinct_dest_zips", 0) >= 5 and postal:
        out.append(
            {
                "category": "network",
                "priority": "low",
                "title": "Rate-shop outbound with multi-zone logic from your DC",
                "detail": (
                    f"Primary origin postal {postal} likely serves a regional share of orders; farther zones "
                    "cost more unless you add nodes. Upload label facts (weight, zones, carrier) from this DC "
                    "so the spine can benchmark spend and flag rate-shop savings."
                ),
                "actions": [
                    "Upload labels.csv mapped with origin_postal = DC ZIP",
                    "Run parcel rate-shop or integrated compare when API keys are set",
                ],
            }
        )

    if len(labels) == 0 and len(order_lines) > 0:
        out.append(
            {
                "category": "parcel",
                "priority": "medium",
                "title": "Add shipment/label rows for rate shopping",
                "detail": (
                    "Order lines alone do not carry parcel weight, service level, or negotiated rates. "
                    "Label-level data enables multi-zone rate shopping versus benchmarks."
                ),
                "actions": ["Upload labels with dest_postal, weight_lb, label_amount_usd, carrier"],
            }
        )

    vb = wi.get("volume_baseline") or {}
    lb = wi.get("labor_baseline") or {}
    if isinstance(vb, dict) and isinstance(lb, dict):
        opm = vb.get("orders_per_month_estimate")
        hc = wi.get("headcount_used")
        if opm and hc and int(hc) > 0:
            try:
                o = float(opm)
                h = float(hc)
                per_fte = o / h if h else None
            except (TypeError, ValueError):
                per_fte = None
            if per_fte is not None:
                out.append(
                    {
                        "category": "operations",
                        "priority": "low",
                        "title": "Orders-per-month vs headcount baseline",
                        "detail": (
                            f"Rough read from shipped dates: ~{per_fte:.0f} distinct orders per month per FTE in the sample window "
                            f"({vb.get('distinct_orders_in_window')} orders over ~{vb.get('months_in_window_fractional', 0):.1f} mo). "
                            "Use as a planning anchor only — tie to your WMS picks and scheduled hours."
                        ),
                        "actions": ["Compare to internal SLA and staffing model", "Upload real task export for true picks/hour"],
                    }
                )

    if not out and grain.order_lines.row_count == 0:
        out.append(
            {
                "category": "data",
                "priority": "medium",
                "title": "Upload order lines and billing to anchor warehouse economics",
                "detail": "No order-line grain yet — network and handle economics need shipped orders plus mapped billing.",
                "actions": [],
            }
        )

    kp = competitive_kpis if isinstance(competitive_kpis, dict) else {}
    if kp.get("schema_version"):
        fixed_share = kp.get("billing_fixed_share_of_total_pct")
        if isinstance(fixed_share, (int, float)) and fixed_share >= 65:
            out.append(
                {
                    "category": "cost_structure",
                    "priority": "high",
                    "title": "Fixed charges dominate billing — isolate variable fulfillment handle",
                    "detail": (
                        f"~{fixed_share:.1f}% of billed USD sits in fixed-like fee codes. "
                        "Competitive benchmarking should compare variable pick/pack to reference handles, not blended invoice totals."
                    ),
                    "actions": [
                        "Re-map fee_code into fixed_period vs variable_ops (see billing_components_usd)",
                        "Compare estimated_cost_per_fulfillment_usd to reference handle in competitive_kpis",
                    ],
                }
            )
        h2r = kp.get("handle_to_reference_typical_ratio")
        if isinstance(h2r, (int, float)) and h2r >= 2.0:
            ref = kp.get("reference_typical_handle_usd")
            est = kp.get("estimated_handle_usd")
            out.append(
                {
                    "category": "competitive_positioning",
                    "priority": "medium",
                    "title": "Variable handle looks high vs typical pick/pack reference",
                    "detail": (
                        f"Estimated variable handle ~${est} vs reference ~${ref} (ratio {h2r:.2f}). "
                        "Validate fee allocation before treating as pure pass-through margin pressure."
                    ),
                    "actions": ["Audit FBM pick/pack lines vs rate card", "Exclude FBA prep from per-parcel handle"],
                }
            )
        nm = kp.get("seller_net_margin_pct")
        rev = kp.get("seller_revenue_usd_total")
        try:
            rev_f = float(rev) if rev is not None else 0.0
        except (TypeError, ValueError):
            rev_f = 0.0
        if nm is not None and rev_f > 0 and float(nm) < 4.0:
            out.append(
                {
                    "category": "margin",
                    "priority": "medium",
                    "title": "Seller net margin is thin in the order_financials window",
                    "detail": (
                        f"CSV-reported net margin ~{float(nm):.2f}% on ~${rev_f:,.0f} revenue — "
                        "stress-test 3PL pass-through and fee escalators against this headroom."
                    ),
                    "actions": ["Reconcile order_financials profit basis vs marketplace fees", "Model fee pass-through in renewals"],
                }
            )
        opf = kp.get("orders_per_fte_month_estimate")
        if isinstance(opf, (int, float)) and opf > 0 and opf < 400:
            out.append(
                {
                    "category": "operations",
                    "priority": "low",
                    "title": "Orders-per-FTE/month is below common high-volume benchmarks",
                    "detail": (
                        f"Rough read ~{opf:.0f} orders/FTE/month from shipped dates and headcount — "
                        "use only as a planning anchor; upload real tasks for true labor throughput."
                    ),
                    "actions": ["Compare to internal SLA", "Upload WMS tasks for picks/hour truth"],
                }
            )

    return out

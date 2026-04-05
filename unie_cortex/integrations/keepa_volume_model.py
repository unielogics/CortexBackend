"""
Category-aware volume reconciliation: sales-rank momentum + review velocity + learned per-category scale.

Feeds adjusted ASIN-level monthly mid/low/high before seller-scoped planning in keepa_demand.
"""

from __future__ import annotations

import math
from typing import Any

from unie_cortex.integrations.volume_calibration_store import category_scale_from_state, load_calibration_state

# Keepa product ``csv`` section types (US marketplace) — see Keepa Product.java.
_KEEPA_CSV_SALES_RANK = 3
_KEEPA_CSV_COUNT_REVIEWS = 17


def _parse_keepa_csv_sections(csv_list: list[int]) -> dict[int, list[int]]:
    sections: dict[int, list[int]] = {}
    i = 0
    n = len(csv_list)
    while i + 1 < n:
        try:
            ctype = int(csv_list[i])
            ln = int(csv_list[i + 1])
        except (TypeError, ValueError):
            break
        i += 2
        if ln < 0 or i + ln > n:
            break
        sections[ctype] = list(csv_list[i : i + ln])
        i += ln
    return sections


def _safe_int(x: Any) -> int | None:
    if x is None:
        return None
    try:
        v = int(x)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def _rank_pairs_from_product(p: dict[str, Any]) -> list[tuple[int, int]]:
    csv_list = p.get("csv")
    lu = _safe_int(p.get("lastUpdate"))
    if not isinstance(csv_list, list) or not lu:
        return []
    try:
        as_ints = [int(x) for x in csv_list]
    except (TypeError, ValueError):
        return []
    sections = _parse_keepa_csv_sections(as_ints)
    rank_chunk = sections.get(_KEEPA_CSV_SALES_RANK) or []
    pairs: list[tuple[int, int]] = []
    for j in range(0, len(rank_chunk) - 1, 2):
        try:
            t = int(rank_chunk[j])
            rnk = int(rank_chunk[j + 1])
        except (TypeError, ValueError):
            continue
        if rnk > 0:
            pairs.append((t, rnk))
    pairs.sort(key=lambda x: x[0])
    return pairs


def _value_at_or_before(pairs: list[tuple[int, int]], t_target: int) -> int | None:
    last: int | None = None
    for t, v in pairs:
        if t > t_target:
            break
        last = v
    return last


def _review_pairs_from_product(p: dict[str, Any]) -> list[tuple[int, int]]:
    csv_list = p.get("csv")
    if not isinstance(csv_list, list):
        return []
    try:
        as_ints = [int(x) for x in csv_list]
    except (TypeError, ValueError):
        return []
    sections = _parse_keepa_csv_sections(as_ints)
    chunk = sections.get(_KEEPA_CSV_COUNT_REVIEWS) or []
    pairs: list[tuple[int, int]] = []
    for j in range(0, len(chunk) - 1, 2):
        try:
            t = int(chunk[j])
            cnt = int(chunk[j + 1])
        except (TypeError, ValueError):
            continue
        if cnt >= 0:
            pairs.append((t, cnt))
    pairs.sort(key=lambda x: x[0])
    return pairs


def _listing_review_total(p: dict[str, Any]) -> int | None:
    for k in ("reviews", "reviewsTotal", "numberOfReviews", "reviewCount"):
        v = _safe_int(p.get(k))
        if v is not None:
            return v
    st = p.get("stats")
    if isinstance(st, dict):
        v = _safe_int(st.get("reviewCount"))
        if v is not None:
            return v
        cur = st.get("current")
        if isinstance(cur, dict):
            v = _safe_int(cur.get("reviewCount"))
            if v is not None:
                return v
    return None


def normalize_category_key(root_category: Any, product_group: Any, binding: Any) -> str:
    parts = [str(root_category or "").strip(), str(product_group or "").strip(), str(binding or "").strip()]
    core = "|".join(p for p in parts if p)
    return core.lower() if core else "unknown"


def default_review_velocity_baseline(category_primary: str | None) -> float:
    """Expected ~new reviews per 30d for a 'typical' moving SKU in this department (tunable prior)."""
    if not category_primary:
        return 4.0
    s = str(category_primary).lower()
    if any(x in s for x in ("book", "textbook", "media")):
        return 2.5
    if any(x in s for x in ("grocery", "food", "perishable", "wine")):
        return 9.0
    if any(x in s for x in ("electronics", "computer", "camera", "phone")):
        return 5.5
    if any(x in s for x in ("apparel", "clothing", "shoe", "jewelry")):
        return 6.0
    if any(x in s for x in ("toy", "game", "baby")):
        return 5.0
    if any(x in s for x in ("industrial", "tool", "hardware", "automotive")):
        return 2.0
    return 4.0


def _drops_30_from_stats(p: dict[str, Any]) -> int | None:
    st = p.get("stats")
    if not isinstance(st, dict):
        return None
    v = _safe_int(st.get("salesRankDrops30"))
    if v is not None:
        return v
    cur = st.get("current")
    if isinstance(cur, dict):
        return _safe_int(cur.get("salesRankDrops30"))
    return None


def build_volume_signals(
    p: dict[str, Any],
    *,
    category_primary: str | None,
    last_update_override: int | None = None,
) -> dict[str, Any]:
    """
    30d-window signals from Keepa csv + stats.

    sales_rank_delta_numeric: rank_now - rank_30d_ago (positive => worse / slipped).
    """
    lu = _safe_int(last_update_override) or _safe_int(p.get("lastUpdate"))
    window_mins = 30 * 1440
    t_end = int(lu or 0)
    t_start = t_end - window_mins if t_end else 0

    rank_pairs = _rank_pairs_from_product(p)
    rank_now = _sales_rank_point_in_time(p, rank_pairs, t_end)
    rank_then = _value_at_or_before(rank_pairs, t_start) if rank_pairs and t_end else None
    if rank_now is None and rank_pairs:
        rank_now = rank_pairs[-1][1]
    delta = None
    improved: bool | None = None
    if rank_now is not None and rank_then is not None:
        delta = int(rank_now) - int(rank_then)
        improved = delta < 0

    rev_pairs = _review_pairs_from_product(p)
    rev_now = _value_at_or_before(rev_pairs, t_end) if rev_pairs and t_end else None
    rev_then = _value_at_or_before(rev_pairs, t_start) if rev_pairs and t_end else None
    listing_rev = _listing_review_total(p)
    if rev_now is None and listing_rev is not None:
        rev_now = listing_rev
    new_reviews_30d: int | None = None
    if rev_now is not None and rev_then is not None:
        new_reviews_30d = max(0, int(rev_now) - int(rev_then))

    drops_30 = _drops_30_from_stats(p)

    cat_key = normalize_category_key(
        p.get("rootCategory"), p.get("productGroup"), p.get("binding")
    )
    baseline_r = default_review_velocity_baseline(category_primary)

    status = "complete"
    notes: list[str] = []
    if not lu:
        status = "partial"
        notes.append("missing lastUpdate — rank/review deltas not anchored")
    if rank_now is None:
        status = "partial"
        notes.append("no sales rank series — momentum unknown")
    if new_reviews_30d is None:
        notes.append("review history unavailable — using rank-only relational adjustment")

    review_ratio = None
    if new_reviews_30d is not None and baseline_r > 0:
        review_ratio = min(4.0, new_reviews_30d / baseline_r)

    return {
        "status": status,
        "category_key": cat_key,
        "sales_rank_current": rank_now,
        "sales_rank_30d_ago": rank_then,
        "sales_rank_delta_numeric": delta,
        "sales_rank_improved_30d": improved,
        "new_reviews_30d": new_reviews_30d,
        "review_count_current": rev_now,
        "review_velocity_baseline_30d": round(baseline_r, 4),
        "review_velocity_ratio_vs_category_prior": round(review_ratio, 4) if review_ratio is not None else None,
        "sales_rank_drops_30_keepa": drops_30,
        "notes": notes,
    }


def _sales_rank_point_in_time(
    p: dict[str, Any],
    rank_pairs: list[tuple[int, int]],
    t_end: int,
) -> int | None:
    v = _value_at_or_before(rank_pairs, t_end)
    if v is not None:
        return v
    st = p.get("stats") or {}
    cur = st.get("current")
    if isinstance(cur, (list, tuple)) and len(cur) > 3:
        return _safe_int(cur[3])
    if isinstance(cur, dict):
        return _safe_int(cur.get("salesRank") or cur.get("salesRankDrops30"))
    return _safe_int(p.get("salesRank"))


def classify_regime(signals: dict[str, Any]) -> str:
    delta = signals.get("sales_rank_delta_numeric")
    improved = signals.get("sales_rank_improved_30d")
    nrev = signals.get("new_reviews_30d")
    rr = signals.get("review_velocity_ratio_vs_category_prior")
    rank_now = signals.get("sales_rank_current")

    if not isinstance(delta, int):
        if isinstance(nrev, int) and nrev >= 3:
            return "review_led_uncertain_rank"
        return "neutral"

    # Strong rank slip while reviews still show up (lag / slowdown).
    if isinstance(nrev, int) and nrev >= 2 and delta > max(200, int(0.08 * (signals.get("sales_rank_30d_ago") or delta))):
        return "rank_slip_with_reviews"

    # Traction: reviews above baseline and rank improving.
    if improved and isinstance(nrev, int) and nrev >= 1:
        if isinstance(rr, (int, float)) and float(rr) >= 1.0:
            return "aligned_acceleration"
        return "rank_improving"

    # Hot shelf: already strong BSR and elevated review pace.
    if isinstance(rank_now, int) and rank_now <= 8000 and isinstance(rr, (int, float)) and float(rr) >= 1.2:
        return "strong_listing_high_review_pace"

    if improved:
        return "rank_improving"

    if isinstance(nrev, int) and nrev >= 4 and not improved and delta >= 0:
        return "review_led_flat_rank"

    return "neutral"


def relational_multiplier(regime: str, signals: dict[str, Any]) -> float:
    """Small bounded nudge from rank↔review concordance (before learned category scale)."""
    rr = signals.get("review_velocity_ratio_vs_category_prior")
    rr_f = float(rr) if isinstance(rr, (int, float)) else 1.0
    delta = signals.get("sales_rank_delta_numeric")
    mag = 0.0
    if isinstance(delta, int):
        mag = min(1.0, abs(delta) / 25_000.0)

    if regime == "rank_slip_with_reviews":
        return max(0.82, 1.0 - 0.14 * min(1.5, rr_f) - 0.06 * mag)
    if regime == "aligned_acceleration":
        return min(1.18, 1.0 + 0.08 * min(1.5, rr_f) + 0.05 * mag)
    if regime == "strong_listing_high_review_pace":
        return min(1.12, 1.0 + 0.06 * min(1.5, rr_f))
    if regime == "rank_improving":
        return min(1.1, 1.0 + 0.05 + 0.04 * mag)
    if regime == "review_led_uncertain_rank":
        return min(1.06, 1.0 + 0.02 * min(1.2, rr_f))
    if regime == "review_led_flat_rank":
        return max(0.9, 1.0 - 0.04 * min(1.5, rr_f))
    return 1.0


def apply_keepa_volume_intelligence(
    p: dict[str, Any],
    mid: float,
    low: float,
    high: float,
    category_primary: str | None,
    *,
    calibration_path: str | None = None,
    model_version: str = "cortex_volume_v1",
) -> dict[str, Any]:
    """
    Adjust ASIN-level monthly band using relational signals + optional learned category scale.

    Returns dict with keys: mid, low, high, meta (for demand JSON).
    """
    signals = build_volume_signals(p, category_primary=category_primary)
    regime = classify_regime(signals)
    rel = relational_multiplier(regime, signals)

    state = load_calibration_state(calibration_path)
    cat_key = str(signals.get("category_key") or "unknown")
    learned, n_s = category_scale_from_state(state, cat_key)

    combined = max(0.35, min(4.0, learned * rel))
    new_mid = round(max(0.01, float(mid) * combined), 2)
    scale = new_mid / float(mid) if mid > 0 else 1.0
    new_low = round(max(0.01, float(low) * scale), 2)
    new_high = round(max(new_low, float(high) * scale), 2)

    rev_imp = implied_monthly_units_from_reviews(
        signals.get("new_reviews_30d") if isinstance(signals.get("new_reviews_30d"), int) else None,
        category_primary=category_primary,
    )
    meta = {
        "status": signals.get("status"),
        "model_version": model_version,
        "regime": regime,
        "relational_multiplier": round(rel, 6),
        "learned_category_scale": round(learned, 6),
        "combined_multiplier": round(combined, 6),
        "calibration_samples_for_category": n_s,
        "review_implied_monthly_units_prior": rev_imp,
        "signals": {k: v for k, v in signals.items() if k != "notes"},
        "notes": list(signals.get("notes") or []),
        "regime_note": _regime_note(regime),
    }
    return {"mid": new_mid, "low": new_low, "high": new_high, "meta": meta}


def _regime_note(regime: str) -> str:
    return {
        "rank_slip_with_reviews": "Sales rank slipped over 30d while reviews still arrived — volume estimate nudged down.",
        "aligned_acceleration": "Reviews above category pace and rank improved — volume estimate nudged up.",
        "strong_listing_high_review_pace": "Strong BSR with fast review pace — modest upward nudge.",
        "rank_improving": "Sales rank improved over 30d — modest upward nudge.",
        "review_led_uncertain_rank": "Review activity without reliable rank delta — small upward uncertainty nudge.",
        "review_led_flat_rank": "Reviews active but rank not improving — slight downward nudge.",
        "neutral": "No strong rank↔review divergence signal.",
    }.get(regime, "")


def build_volume_intelligence_without_monthly_baseline(
    p: dict[str, Any],
    category_primary: str | None,
    *,
    gap_reason: str,
    model_version: str,
    calibration_path: str | None,
) -> dict[str, Any]:
    """
    When Keepa has no monthlySold and no usable sales rank, still attach rank/review signals + regime for UX
    and calibration context (no ASIN monthly band to multiply).
    """
    signals = build_volume_signals(p, category_primary=category_primary)
    regime = classify_regime(signals)
    state = load_calibration_state(calibration_path)
    cat_key = str(signals.get("category_key") or "unknown")
    learned, n_s = category_scale_from_state(state, cat_key)
    nrev = signals.get("new_reviews_30d") if isinstance(signals.get("new_reviews_30d"), int) else None
    rev_imp = implied_monthly_units_from_reviews(nrev, category_primary=category_primary)
    notes = list(signals.get("notes") or [])
    notes.append(gap_reason)
    return {
        "status": "partial_no_monthly_baseline",
        "listing_gap_reason": gap_reason,
        "model_version": model_version,
        "regime": regime,
        "relational_multiplier": None,
        "learned_category_scale": round(learned, 6),
        "combined_multiplier": None,
        "calibration_samples_for_category": n_s,
        "review_implied_monthly_units_prior": rev_imp,
        "signals": {k: v for k, v in signals.items() if k != "notes"},
        "notes": notes,
        "regime_note": _regime_note(regime),
    }


def implied_monthly_units_from_reviews(
    new_reviews_30d: int | None,
    *,
    category_primary: str | None,
    review_to_sales_prior: float | None = None,
) -> float | None:
    """
    Secondary cross-check: orders ≈ reviews × (1 / review_rate).

    review_to_sales_prior: fraction of orders that yield a review; if None, derived from category baseline.
    """
    if new_reviews_30d is None or new_reviews_30d <= 0:
        return None
    base_r = default_review_velocity_baseline(category_primary)
    # Rough prior: if baseline expects 4 reviews/mo at ~X sales, implied review rate ~ baseline/scale — use invertible prior.
    if review_to_sales_prior is not None and 0 < review_to_sales_prior < 0.5:
        rate = float(review_to_sales_prior)
    else:
        rate = max(0.01, min(0.25, 0.18 / math.sqrt(max(base_r, 1.0))))
    return round(float(new_reviews_30d) / rate, 2)

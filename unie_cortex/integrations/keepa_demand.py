"""
Deterministic demand + listing intelligence from Keepa product JSON.

Caches full API payload in keepa_snapshots (TTL from KEEPA_TTL_DAYS); this module extracts
title/category/seller-snapshot signals, category-tuned velocity, buy-box context, and placement copy.

Time-series (sales rank, buy-box price history, etc.) are read from each payload's ``csv`` / ``stats``,
not inferred from ``offers[]`` row counts.
"""

from __future__ import annotations

import math
from typing import Any

KEEPA_OFFERS_DIGEST_VERSION = "keepa_offers_digest_v1"
KEEPA_TREND_BUNDLE_VERSION = "keepa_trend_bundle_v1"


def _safe_int(x: Any) -> int | None:
    if x is None:
        return None
    try:
        v = int(x)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def _sales_rank_from_product(p: dict[str, Any]) -> int | None:
    st = p.get("stats") or {}
    cur = st.get("current")
    if isinstance(cur, (list, tuple)) and len(cur) > 3:
        return _safe_int(cur[3])
    if isinstance(cur, dict):
        return _safe_int(cur.get("salesRank") or cur.get("salesRankDrops30"))
    return _safe_int(p.get("salesRank")) or _safe_int(p.get("currentSalesRank"))


def _rank_to_monthly_units_band(rank: int) -> tuple[float, float]:
    """
    Very rough US marketplace proxy (category tuning applied separately).
    mid ≈ k / rank^alpha; band 0.4x–2.5x.
    """
    if rank <= 0:
        return 0.0, 0.0
    mid = 960_000.0 / (rank**0.87)
    mid = max(1.0, min(mid, 500_000.0))
    return round(mid * 0.4, 2), round(mid * 2.5, 2)


def category_velocity_factor(category_primary: str | None) -> float:
    """
    Lightweight multipliers until category-specific rank curves are calibrated.
    """
    if not category_primary:
        return 1.0
    s = str(category_primary).lower()
    if any(x in s for x in ("book", "textbook", "media")):
        return 0.92
    if any(x in s for x in ("grocery", "food", "perishable", "wine")):
        return 1.08
    if any(x in s for x in ("electronics", "computer", "camera", "phone")):
        return 1.05
    if any(x in s for x in ("apparel", "clothing", "shoe", "jewelry")):
        return 1.02
    if any(x in s for x in ("toy", "game", "baby")):
        return 1.03
    return 1.0


def extract_listing_profile(p: dict[str, Any]) -> dict[str, Any]:
    """Title, category hints, identifiers — safe for re-display without another Keepa call."""
    title = (p.get("title") or "").strip() or None
    labels: list[str] = []
    root = p.get("rootCategory")
    if root is not None:
        labels.append(str(root))
    pg = p.get("productGroup")
    if pg:
        labels.append(str(pg))
    b = p.get("binding")
    if b:
        labels.append(str(b))
    cat_primary = labels[0] if labels else None
    return {
        "title": title,
        "manufacturer": p.get("manufacturer") or p.get("brand"),
        "product_group": p.get("productGroup"),
        "binding": p.get("binding"),
        "root_category": p.get("rootCategory"),
        "category_labels_guess": labels[:8],
        "category_primary_for_heuristics": cat_primary,
        "parent_asin": p.get("parentAsin"),
        "ean": p.get("ean") or p.get("eanList"),
        "upc": p.get("upc") or p.get("upcList"),
    }


def classify_offer_condition(o: dict[str, Any]) -> str:
    """
    Tri-state Keepa ``condition``: ``new`` (code 1), ``used_like`` (other known codes / keywords),
    or ``unknown`` (missing / empty / unparseable).
    """
    c = o.get("condition")
    if c is None:
        return "unknown"
    try:
        ic = int(c)
        return "new" if ic == 1 else "used_like"
    except (TypeError, ValueError):
        pass
    s = str(c).strip().lower()
    if not s:
        return "unknown"
    if s in ("1", "new"):
        return "new"
    if "used" in s or s in ("2", "3", "4", "5", "refurb", "collectible"):
        return "used_like"
    return "unknown"


def _offer_condition_code_raw(o: dict[str, Any]) -> str | None:
    c = o.get("condition")
    if c is None:
        return None
    return str(c).strip() or None


def _offer_counts_as_new_listing_path(o: dict[str, Any], *, assume_unknown_condition_is_new: bool) -> bool:
    b = classify_offer_condition(o)
    if b == "new":
        return True
    if b == "used_like":
        return False
    return bool(assume_unknown_condition_is_new)


def _offer_landed_usd_from_row(o: dict[str, Any]) -> float | None:
    """
    Best-effort landed price for an offer row: (price + shipping) in USD when both are int cents;
    else price alone if present. Keepa uses integer cents for marketplace currency.
    """
    price = o.get("price")
    ship = o.get("shipping")
    try:
        pc = int(price) if price is not None else None
    except (TypeError, ValueError):
        pc = None
    try:
        sc = int(ship) if ship is not None else None
    except (TypeError, ValueError):
        sc = None
    if pc is not None and pc > 0:
        total_cents = pc + (sc if sc is not None and sc > 0 else 0)
        return round(float(total_cents) / 100.0, 4)
    return None


def normalize_offers_by_seller(
    offers: list[Any] | None,
    *,
    assume_unknown_condition_is_new: bool,
    max_sellers: int = 250,
    lu_minute: int | None = None,
) -> dict[str, Any]:
    """
    One aggregate per distinct ``sellerId``: row counts, condition flags, Amazon/FBA/Prime, min new-path landed USD.

    Rows without ``sellerId`` are counted in ``offer_rows_without_seller_id`` only.
    """
    if not isinstance(offers, list) or not offers:
        return {
            "digest_version": KEEPA_OFFERS_DIGEST_VERSION,
            "assume_unknown_condition_is_new": assume_unknown_condition_is_new,
            "last_update_minute": lu_minute,
            "offer_row_count_total": 0,
            "offer_rows_without_seller_id": 0,
            "unique_merchants_all_conditions": 0,
            "unique_merchants_new_only": 0,
            "amazon_merchants": 0,
            "amazon_flagged_offer_rows": 0,
            "unknown_condition_offer_rows": 0,
            "offers_by_seller": [],
            "truncated": False,
        }

    by_sid: dict[str, dict[str, Any]] = {}
    no_sid = 0
    amazon_rows = 0
    unknown_rows = 0

    for raw in offers:
        if not isinstance(raw, dict):
            continue
        o = raw
        sid_raw = o.get("sellerId")
        if sid_raw is None or not str(sid_raw).strip():
            no_sid += 1
            continue
        sid = str(sid_raw).strip()
        bucket = classify_offer_condition(o)
        if bucket == "unknown":
            unknown_rows += 1
        is_amz = _offer_amazon_flag(o)
        if is_amz:
            amazon_rows += 1
        fba = o.get("isFBA")
        if fba is None:
            fba = o.get("fba")
        is_fba = fba in (True, 1, "1", "true", "True")
        prime = o.get("isPrime")
        if prime is None:
            prime = o.get("prime")
        is_prime = prime in (True, 1, "1", "true", "True")
        landed = _offer_landed_usd_from_row(o)
        new_path = _offer_counts_as_new_listing_path(o, assume_unknown_condition_is_new=assume_unknown_condition_is_new)
        code_raw = _offer_condition_code_raw(o)

        rec = by_sid.get(sid)
        if rec is None:
            rec = {
                "seller_id": sid,
                "offer_row_count": 0,
                "condition_codes": set(),
                "has_new": False,
                "has_used_like": False,
                "has_unknown": False,
                "is_amazon": False,
                "has_fba": False,
                "has_prime": False,
                "min_new_landed_usd": None,
            }
            by_sid[sid] = rec

        rec["offer_row_count"] += 1
        if code_raw is not None:
            rec["condition_codes"].add(code_raw)
        if bucket == "new":
            rec["has_new"] = True
        elif bucket == "used_like":
            rec["has_used_like"] = True
        else:
            rec["has_unknown"] = True
        if is_amz:
            rec["is_amazon"] = True
        if is_fba:
            rec["has_fba"] = True
        if is_prime:
            rec["has_prime"] = True
        if new_path and landed is not None:
            prev = rec["min_new_landed_usd"]
            rec["min_new_landed_usd"] = landed if prev is None else min(prev, landed)

    merchants_all = len(by_sid)
    merchants_new = 0
    for r in by_sid.values():
        if r["has_new"] or (assume_unknown_condition_is_new and r["has_unknown"]):
            merchants_new += 1

    amazon_merchants = sum(1 for r in by_sid.values() if r["is_amazon"])

    sorted_sellers = sorted(by_sid.values(), key=lambda x: (-int(x["offer_row_count"]), x["seller_id"]))
    truncated = len(sorted_sellers) > max_sellers
    slim: list[dict[str, Any]] = []
    for r in sorted_sellers[:max_sellers]:
        codes = sorted(r["condition_codes"])
        slim.append(
            {
                "seller_id": r["seller_id"],
                "offer_row_count": r["offer_row_count"],
                "condition_codes": codes,
                "has_new": r["has_new"],
                "has_used_like": r["has_used_like"],
                "has_unknown": r["has_unknown"],
                "is_amazon": r["is_amazon"],
                "has_fba": r["has_fba"],
                "has_prime": r["has_prime"],
                "min_new_landed_usd": r["min_new_landed_usd"],
            }
        )

    return {
        "digest_version": KEEPA_OFFERS_DIGEST_VERSION,
        "assume_unknown_condition_is_new": assume_unknown_condition_is_new,
        "last_update_minute": lu_minute,
        "offer_row_count_total": sum(r["offer_row_count"] for r in by_sid.values()) + no_sid,
        "offer_rows_without_seller_id": no_sid,
        "offer_rows_with_seller_id": sum(r["offer_row_count"] for r in by_sid.values()),
        "unique_merchants_all_conditions": merchants_all,
        "unique_merchants_new_only": merchants_new,
        "amazon_merchants": amazon_merchants,
        "amazon_flagged_offer_rows": amazon_rows,
        "unknown_condition_offer_rows": unknown_rows,
        "offers_by_seller": slim,
        "truncated": truncated,
    }


def extract_seller_landscape_from_offers(
    p: dict[str, Any],
    buy_box_seller_id: str | None,
    offers_digest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    **Offer-row concentration** in the current Keepa snapshot — not % of sales or buy-box time.
    Useful when one seller id owns most rows (often brand/retail) vs fragmented 3P.

    Row-share denominators use rows that carry a ``sellerId`` (same as pre-digest behavior).
    When ``offers_digest`` is passed, merchant totals align with the regulated digest.
    """
    offers = p.get("offers")
    if not isinstance(offers, list) or not offers:
        return {
            "status": "partial",
            "note": "No offers[] on product — set KEEPA_PRODUCT_OFFERS>0 and refresh.",
        }
    offer_list_len = sum(1 for x in offers if isinstance(x, dict))
    counts: dict[str, int] = {}
    for o in offers:
        if not isinstance(o, dict):
            continue
        sid = o.get("sellerId")
        if sid is None:
            continue
        k = str(sid)
        counts[k] = counts.get(k, 0) + 1
    total = sum(counts.values())
    if total <= 0:
        return {"status": "partial", "note": "Offer rows had no sellerId fields."}
    shares = {k: round(v / total, 4) for k, v in counts.items()}
    ranked = sorted(shares.items(), key=lambda x: -x[1])
    top_sid, top_share = ranked[0]
    bb = str(buy_box_seller_id).strip() if buy_box_seller_id else None
    bb_is_top = bb == top_sid if bb else None
    if top_share >= 0.9:
        interp = "single_seller_dominates_offer_snapshot"
    elif top_share >= 0.65:
        interp = "likely_leader_in_snapshot_not_sales_proof"
    else:
        interp = "fragmented_offer_snapshot"
    out: dict[str, Any] = {
        "status": "complete",
        "offer_rows_counted": total,
        "offer_rows_total_in_payload": offer_list_len,
        "unique_sellers_in_snapshot": len(shares),
        "seller_row_share_top": [{"seller_id": ranked[i][0], "row_share": ranked[i][1]} for i in range(min(5, len(ranked)))],
        "top_seller_id_by_rows": top_sid,
        "top_seller_row_share_est": top_share,
        "buy_box_seller_id": bb,
        "buy_box_matches_top_row_seller": bb_is_top,
        "interpretation": interp,
        "third_party_note": (
            "Row shares ≠ buy-box win % or unit sales. Match your seller id for actionable buy-box share."
        ),
    }
    if isinstance(offers_digest, dict) and offers_digest.get("digest_version"):
        out["digest_offer_row_count_total"] = offers_digest.get("offer_row_count_total")
        out["digest_offer_rows_without_seller_id"] = offers_digest.get("offer_rows_without_seller_id")
        out["unique_merchants_all_conditions"] = offers_digest.get("unique_merchants_all_conditions")
        out["unique_merchants_new_only"] = offers_digest.get("unique_merchants_new_only")
    return out


def extract_buybox_signals(
    p: dict[str, Any],
    offers_digest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Lightweight competition / buy-box **context** from Keepa product JSON.

    Requires ``offers`` array on the product (request ``offers`` param on Keepa API).
    Merchant counts use ``offers_digest`` when provided (grouped by sellerId); offer row totals are explicit.
    Does **not** equal a specific seller's buy box % without seller ID matching.
    """
    offers = p.get("offers")
    dig: dict[str, Any] | None = None
    if isinstance(offers_digest, dict) and offers_digest.get("digest_version"):
        dig = offers_digest
    if dig is None and isinstance(offers, list):
        from unie_cortex.config import settings as _s

        dig = normalize_offers_by_seller(
            offers,
            assume_unknown_condition_is_new=bool(
                getattr(_s, "keepa_assume_unknown_condition_is_new", True)
            ),
            max_sellers=int(getattr(_s, "keepa_offers_digest_max_sellers", 250) or 250),
            lu_minute=_safe_int(p.get("lastUpdate")),
        )

    n_offers = int(dig.get("offer_row_count_total") or 0) if dig else 0
    merchants_all = int(dig.get("unique_merchants_all_conditions") or 0) if dig else 0
    merchants_new = int(dig.get("unique_merchants_new_only") or 0) if dig else 0
    amazon_rows = int(dig.get("amazon_flagged_offer_rows") or 0) if dig else 0
    amazon_merchants = int(dig.get("amazon_merchants") or 0) if dig else 0

    m_comp = merchants_new if merchants_new > 0 else merchants_all

    if n_offers >= 20 or m_comp >= 12:
        competition = "high"
    elif n_offers >= 8 or m_comp >= 5:
        competition = "medium"
    elif n_offers > 0:
        competition = "low"
    else:
        competition = "unknown"

    dominance_hint = "unknown"
    if merchants_all > 0 and amazon_merchants >= max(3, int(0.25 * merchants_all)):
        dominance_hint = "amazon_or_retail_strong"
    elif n_offers > 0 and amazon_rows >= max(3, int(0.25 * n_offers)):
        dominance_hint = "amazon_or_retail_strong"
    elif n_offers > 0 and m_comp <= 4 and m_comp > 0:
        dominance_hint = "few_distinct_sellers"

    buy_box_seller_id = p.get("buyBoxSellerId")
    stats = p.get("stats")
    if buy_box_seller_id is None and isinstance(stats, dict):
        buy_box_seller_id = stats.get("buyBoxSellerId")

    return {
        "status": "complete" if n_offers > 0 or buy_box_seller_id else "partial",
        "offer_row_count": n_offers,
        "offer_rows_available": n_offers,
        "unique_merchants_all_conditions": merchants_all,
        "unique_merchants_new_only": merchants_new,
        "unique_seller_ids_est": merchants_all,
        "amazon_flagged_offer_rows": amazon_rows,
        "amazon_merchants_in_snapshot": amazon_merchants,
        "competition_level": competition,
        "dominance_hint": dominance_hint,
        "buy_box_seller_id": str(buy_box_seller_id) if buy_box_seller_id not in (None, "") else None,
        "note": "Marketplace listing competition, not your seller's buy box share unless you match seller IDs.",
    }


# Keepa ``stats.current`` / CSV column indices (Product.java — same as keepa.constants.csv_indices).
_KEEPA_CSV_AMAZON = 0
_KEEPA_CSV_NEW = 1
_KEEPA_CSV_LISTPRICE = 4
_KEEPA_CSV_BUY_BOX_SHIPPING = 18


def _keepa_stat_current_int(cur: Any, index: int) -> int | None:
    if not isinstance(cur, (list, tuple)) or index >= len(cur):
        return None
    raw = cur[index]
    try:
        v = int(raw)
    except (TypeError, ValueError):
        return None
    if v < 0:
        return None
    return v


def _keepa_cents_to_usd(cents: int | None) -> float | None:
    if cents is None:
        return None
    return round(float(cents) / 100.0, 4)


def compute_buy_box_landed_price_7d_reference_stats(
    p: dict[str, Any],
    *,
    days: int = 7,
) -> dict[str, Any] | None:
    """
    Rolling buy-box landed (BUY_BOX_SHIPPING) stats from Keepa ``csv`` history.

    Uses change points in csv type **18** (same index as ``stats.current`` BUY_BOX_SHIPPING).
    Mean/min/max are taken over **distinct price levels** observed after the window start
    (opening level carried into the window, then each new positive price inside the window).
    """
    lu = _safe_int(p.get("lastUpdate"))
    if lu is None or lu <= 0:
        return None
    d = max(int(days), 1)
    window_mins = d * 1440
    t_start = lu - window_mins
    csv_list = p.get("csv")
    if not isinstance(csv_list, list) or len(csv_list) < 4:
        return None
    try:
        as_ints = [int(x) for x in csv_list]
    except (TypeError, ValueError):
        return None
    sections = _parse_keepa_csv_sections(as_ints)
    chunk = sections.get(_KEEPA_CSV_BUY_BOX_SHIPPING) or []
    if len(chunk) < 4:
        return None
    pairs: list[tuple[int, int]] = []
    for j in range(0, len(chunk) - 1, 2):
        try:
            t = int(chunk[j])
            cents = int(chunk[j + 1])
        except (TypeError, ValueError):
            continue
        pairs.append((t, cents))
    pairs.sort(key=lambda x: x[0])
    if not pairs:
        return None

    last: float | None = None
    for t, cents in pairs:
        if t > t_start:
            break
        if cents > 0:
            last = _keepa_cents_to_usd(cents)
        elif cents == -1:
            last = None

    samples: list[float] = []
    if last is not None:
        samples.append(last)

    prev = last
    for t, cents in pairs:
        if t <= t_start or t > lu:
            continue
        if cents > 0:
            cur = _keepa_cents_to_usd(cents)
        elif cents == -1:
            cur = None
        else:
            continue
        if cur is not None and cur != prev:
            samples.append(cur)
        prev = cur

    if not samples:
        return None
    avg = round(sum(samples) / len(samples), 4)
    lo = round(min(samples), 4)
    hi = round(max(samples), 4)
    return {
        "buy_box_landed_avg_7d_usd": avg,
        "buy_box_landed_min_7d_usd": lo,
        "buy_box_landed_max_7d_usd": hi,
        "buy_box_landed_7d_window_days": d,
        "buy_box_landed_7d_sample_count": len(samples),
        "buy_box_landed_7d_note": (
            f"From Keepa csv BUY_BOX_SHIPPING history: mean/min/max of distinct landed buy-box "
            f"levels seen in the last {d} days (change-point sampling; not minute-weighted)."
        ),
    }


def extract_listing_economics_reference_usd(p: dict[str, Any]) -> dict[str, Any]:
    """
    Current reference prices from Keepa ``stats.current`` for marketplace economics (breakeven, margin ex-COGS).

    ``buy_box_landed_price_usd`` maps Keepa's **BUY_BOX_SHIPPING** column (landed-style buy box as Keepa models it).
    Requires ``stats`` on the product (set ``KEEPA_PRODUCT_STATS_DAYS`` > 0).
    """
    st = p.get("stats")
    if not isinstance(st, dict):
        return {
            "status": "partial",
            "source": "keepa",
            "note": "no stats on product — enable KEEPA_PRODUCT_STATS_DAYS for buy box / list prices",
        }
    cur = st.get("current")
    bb_cents = _keepa_stat_current_int(cur, _KEEPA_CSV_BUY_BOX_SHIPPING)
    list_cents = _keepa_stat_current_int(cur, _KEEPA_CSV_LISTPRICE)
    new_cents = _keepa_stat_current_int(cur, _KEEPA_CSV_NEW)
    amz_cents = _keepa_stat_current_int(cur, _KEEPA_CSV_AMAZON)
    buy_box = _keepa_cents_to_usd(bb_cents)
    out: dict[str, Any] = {
        "status": "complete" if buy_box is not None else "partial",
        "source": "keepa_stats_current",
        "buy_box_landed_price_usd": buy_box,
        "list_price_usd": _keepa_cents_to_usd(list_cents),
        "new_offer_price_usd": _keepa_cents_to_usd(new_cents),
        "amazon_price_usd": _keepa_cents_to_usd(amz_cents),
        "keepa_csv_indices": {
            "buy_box_landed": _KEEPA_CSV_BUY_BOX_SHIPPING,
            "list_price": _KEEPA_CSV_LISTPRICE,
            "new": _KEEPA_CSV_NEW,
            "amazon": _KEEPA_CSV_AMAZON,
        },
        "note": (
            "Prices from Keepa stats.current (cents→USD). BUY_BOX_SHIPPING is the standard buy-box reference "
            "for listing economics; COGS/fees are not subtracted."
        ),
    }
    roll = compute_buy_box_landed_price_7d_reference_stats(p, days=7)
    if roll:
        out.update(roll)
    return out


def extract_buybox_stats_light(p: dict[str, Any]) -> dict[str, Any]:
    """Surface any buy-box-adjacent flags Keepa exposes on ``stats`` (varies by API version)."""
    st = p.get("stats")
    if not isinstance(st, dict):
        return {"status": "partial", "note": "no stats object on product"}
    out: dict[str, Any] = {"status": "complete"}
    for k in ("buyBoxIsAmazon", "buyBoxIsUnqualified", "buyBoxIsPrimeExclusive", "isSNS"):
        if k in st:
            out[k] = st.get(k)
    cur = st.get("current")
    if isinstance(cur, (list, tuple)):
        out["stats_current_array_len"] = len(cur)
    keys = [x for x in st.keys() if isinstance(x, str)]
    out["stats_keys_sample"] = sorted(keys)[:30]
    return out


def _parse_buybox_seller_id_history(history: Any) -> list[tuple[int, str]]:
    """
    Keepa ``buyBoxSellerIdHistory``: ordered ``[keepaMinute, sellerId, ...]`` (see Keepa Product.java).
    ``-1`` = no buy box qualified; ``-2`` = unknown new seller.
    """
    if history is None:
        return []
    seq: list[str] = []
    if isinstance(history, str):
        seq = [x.strip() for x in history.replace(";", ",").split(",") if x.strip()]
    elif isinstance(history, list):
        seq = [str(x).strip() for x in history if str(x).strip()]
    pairs: list[tuple[int, str]] = []
    i = 0
    while i + 1 < len(seq):
        try:
            t = int(seq[i])
            sid = str(seq[i + 1]).strip()
            pairs.append((t, sid))
        except (ValueError, TypeError):
            pass
        i += 2
    pairs.sort(key=lambda x: x[0])
    return pairs


def _is_real_marketplace_seller(seller_id: str) -> bool:
    return bool(seller_id) and seller_id not in ("-1", "-2")


def _buybox_window_durations(
    pairs: list[tuple[int, str]], t_end: int, window_mins: int
) -> tuple[dict[str, float], float]:
    """Return per-seller minutes holding buy box within [t_end - window, t_end]."""
    if not pairs or t_end <= 0 or window_mins <= 0:
        return {}, 0.0
    t_start = max(0, int(t_end) - int(window_mins))
    dur: dict[str, float] = {}
    total = 0.0
    for i, (t_s, sid) in enumerate(pairs):
        t_e = pairs[i + 1][0] if i + 1 < len(pairs) else int(t_end)
        a = max(int(t_s), t_start)
        b = min(int(t_e), int(t_end))
        if b > a:
            w = float(b - a)
            dur[sid] = dur.get(sid, 0.0) + w
            total += w
    return dur, total


def _norm_listing_rating_to_pct(value: Any) -> float | None:
    """Map Keepa / offer rating to ~0–100 positive-feedback style for comparison."""
    if value is None:
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    if x < 0:
        return None
    if x <= 5.5:
        return min(100.0, x * 20.0)
    if x <= 50.0:
        return min(100.0, x * 2.0)
    return min(100.0, x)


def _pick_catalog_field(row: dict[str, Any], *keys: str) -> Any:
    """Prefer top-level catalog keys, then ``extra`` JSON (Product Research form)."""
    for k in keys:
        if k in row and row.get(k) is not None and str(row.get(k)).strip() != "":
            return row.get(k)
    ex = row.get("extra")
    if not isinstance(ex, dict):
        return None
    for k in keys:
        if k in ex and ex.get(k) is not None and str(ex.get(k)).strip() != "":
            return ex.get(k)
    return None


def seller_inputs_from_catalog_row(row: dict[str, Any]) -> dict[str, Any]:
    """
    Resolve Keepa extract inputs from operational catalog row.

    Supported in ``extra`` or top-level: ``marketplace_seller_id``, ``amazon_seller_id``,
    ``seller_listing_rating_12m_pct`` (0–100), ``seller_listing_star_rating`` (1–5 stars),
    ``seller_listing_review_count``, ``seller_listing_is_fba``.
    """
    msid = _pick_catalog_field(row, "marketplace_seller_id", "amazon_seller_id")
    msid = str(msid).strip() if msid is not None else None
    msid = msid or None

    rating_pct: float | None = None
    raw_pct = _pick_catalog_field(row, "seller_listing_rating_12m_pct")
    if raw_pct is not None:
        try:
            rating_pct = float(raw_pct)
        except (TypeError, ValueError):
            rating_pct = None
    if rating_pct is None:
        star = _pick_catalog_field(row, "seller_listing_star_rating", "seller_listing_stars")
        rating_pct = _norm_listing_rating_to_pct(star)

    rev_raw = _pick_catalog_field(row, "seller_listing_review_count")
    review_count: float | None = None
    if rev_raw is not None:
        try:
            review_count = float(rev_raw)
        except (TypeError, ValueError):
            review_count = None

    fba_raw = _pick_catalog_field(row, "seller_listing_is_fba")
    is_fba: bool | None = None
    if fba_raw is not None:
        is_fba = fba_raw in (True, 1, "1", "true", "True")

    return {
        "marketplace_seller_id": msid,
        "seller_listing_rating_12m_pct": rating_pct,
        "seller_listing_review_count": review_count,
        "seller_listing_is_fba": is_fba,
    }


def _peer_trust_distance(
    client_r: float,
    client_rev: float,
    peer_r: float,
    peer_rev: float,
    *,
    w_rev: float,
    w_rat: float,
) -> float:
    import math

    return w_rev * abs(math.log1p(client_rev) - math.log1p(peer_rev)) + w_rat * abs(client_r - peer_r) / 100.0


def _offer_amazon_flag(o: dict[str, Any]) -> bool:
    return o.get("isAmazon") in (True, 1) or o.get("isAmz") in (True, 1)


def _offer_is_used_like(o: dict[str, Any]) -> bool:
    """True only for ``used_like`` — unknown condition is not treated as used."""
    return classify_offer_condition(o) == "used_like"


def _qualified_buy_box_minutes_in_window(
    pairs: list[tuple[int, str]], t_end: int, window_mins: int
) -> float:
    """Minutes within [t_end-window, t_end] where buy box is held by a real marketplace seller id."""
    if not pairs or t_end <= 0 or window_mins <= 0:
        return 0.0
    t_start = max(0, int(t_end) - int(window_mins))
    total = 0.0
    for i, (t_s, sid) in enumerate(pairs):
        t_e = pairs[i + 1][0] if i + 1 < len(pairs) else int(t_end)
        a = max(int(t_s), t_start)
        b = min(int(t_e), int(t_end))
        if b <= a:
            continue
        if _is_real_marketplace_seller(str(sid).strip()):
            total += float(b - a)
    return total


def build_inventory_suggestion_guardrails(
    p: dict[str, Any],
    *,
    buybox_stats_light: dict[str, Any] | None = None,
    buy_box_rotation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    UX / risk flags for procurement and monthly-unit suggestions (Product Research).

    - Surfaces Amazon-new-only listings (no 3P new offers in Keepa snapshot).
    - Documents that used-condition offers are not modeled in planning velocity.
    - Buy-box history: lack of qualified seller time in 30d / 90d; ephemeral seller stints in 12m.
    """
    offers = p.get("offers") if isinstance(p.get("offers"), list) else []
    bsl = buybox_stats_light if isinstance(buybox_stats_light, dict) else {}
    rot = buy_box_rotation if isinstance(buy_box_rotation, dict) else {}

    from unie_cortex.config import settings as _gs

    assume_new = bool(getattr(_gs, "keepa_assume_unknown_condition_is_new", True))

    used_metrics_note = (
        "Cortex planning velocity and buy-box analytics use the new-condition listing path. "
        "Used, refurbished, and collectible offers in Keepa are not counted toward these metrics."
    )

    amazon_new_offer_rows = 0
    third_party_new_seller_ids: set[str] = set()
    used_like_offer_rows = 0
    unknown_condition_offer_rows = 0
    if offers:
        for raw in offers:
            if not isinstance(raw, dict):
                continue
            o = raw
            if classify_offer_condition(o) == "used_like":
                used_like_offer_rows += 1
                continue
            if not _offer_counts_as_new_listing_path(o, assume_unknown_condition_is_new=assume_new):
                unknown_condition_offer_rows += 1
                continue
            if _offer_amazon_flag(o):
                amazon_new_offer_rows += 1
                continue
            sid = o.get("sellerId")
            if sid is not None and str(sid).strip():
                third_party_new_seller_ids.add(str(sid).strip())

    amazon_bb_hint = bsl.get("buyBoxIsAmazon") in (True, 1)
    amazon_retail_new_in_offers = amazon_new_offer_rows > 0
    no_third_party_new = len(third_party_new_seller_ids) == 0

    offer_snapshot_complete = len(offers) > 0
    amazon_only_new_listing = bool(
        offer_snapshot_complete and amazon_retail_new_in_offers and no_third_party_new
    )

    lu = _safe_int(p.get("lastUpdate")) or 0
    pairs = _parse_buybox_seller_id_history(p.get("buyBoxSellerIdHistory"))
    t_end = int(lu) if lu > 0 else (pairs[-1][0] if pairs else 0)

    mins_30d = _qualified_buy_box_minutes_in_window(pairs, t_end, 30 * 1440) if pairs and t_end > 0 else 0.0
    mins_90d = _qualified_buy_box_minutes_in_window(pairs, t_end, 90 * 1440) if pairs and t_end > 0 else 0.0
    mins_12m = _qualified_buy_box_minutes_in_window(pairs, t_end, 365 * 1440) if pairs and t_end > 0 else 0.0

    no_qualified_buy_box_30d = pairs and t_end > 0 and mins_30d < 60.0
    no_qualified_buy_box_90d = pairs and t_end > 0 and mins_90d < 60.0

    ephemeral_sellers = 0
    if len(pairs) >= 2 and t_end > 0:
        win_mins = int(365 * 1440)
        t_start = max(0, t_end - win_mins)
        per_sid: dict[str, float] = {}
        for i, (t_s, sid) in enumerate(pairs):
            if not _is_real_marketplace_seller(str(sid).strip()):
                continue
            t_e = pairs[i + 1][0] if i + 1 < len(pairs) else int(t_end)
            a = max(int(t_s), t_start)
            b = min(int(t_e), int(t_end))
            if b <= a:
                continue
            k = str(sid).strip()
            per_sid[k] = per_sid.get(k, 0.0) + float(b - a)
        for _sid, m in per_sid.items():
            if 1440.0 <= m <= 10 * 1440.0:
                ephemeral_sellers += 1

    dominant_win = rot.get("dominant_win_pct")
    try:
        dom_pct = float(dominant_win) if dominant_win is not None else None
    except (TypeError, ValueError):
        dom_pct = None

    flags: list[dict[str, Any]] = []
    amz_share_30d = None
    tp_minutes_30d = None
    if pairs and t_end > 0:
        dur30, _tot30 = _buybox_window_durations(pairs, t_end, 30 * 1440)
        real30 = {sid: m for sid, m in dur30.items() if _is_real_marketplace_seller(str(sid))}
        q30 = float(sum(real30.values()))
        amz30 = float(real30.get("ATVPDKIKX0DER", 0.0))
        tp30 = max(0.0, q30 - amz30)
        tp_minutes_30d = round(tp30, 2)
        amz_share_30d = round((100.0 * amz30 / q30), 4) if q30 > 0 else 0.0
        if q30 >= 60.0 and amz_share_30d >= 95.0 and tp30 <= 0.0:
            flags.append(
                {
                    "code": "amazon_buybox_30d_only_high_risk",
                    "severity": "critical",
                    "title": "Amazon controls buy box in last 30 days",
                    "detail": (
                        "Last 30-day buy-box history is effectively Amazon-only with no measurable third-party time-on-box. "
                        "Recommended to sell: NO (high risk unless you are the brand owner / explicitly authorized)."
                    ),
                }
            )
    if amazon_only_new_listing:
        flags.append(
            {
                "code": "amazon_new_no_third_party_new_offers",
                "severity": "critical",
                "title": "Amazon appears to own the new offer",
                "detail": (
                    "Keepa shows Amazon retail on new condition and no third-party sellers in new condition in this "
                    "snapshot. We do not recommend planning inventory for resale unless you are the brand or an "
                    "authorized seller."
                ),
            }
        )
    elif not offer_snapshot_complete and amazon_bb_hint:
        flags.append(
            {
                "code": "buy_box_amazon_hint_no_offer_rows",
                "severity": "warning",
                "title": "Buy box may be Amazon — offer snapshot missing",
                "detail": (
                    "Keepa hints the buy box is Amazon but returned no offer rows — increase Keepa offers/stats depth "
                    "to confirm third-party new sellers before relying on inventory suggestions."
                ),
            }
        )
    if unknown_condition_offer_rows > 0 and not assume_new:
        flags.append(
            {
                "code": "unknown_condition_offer_rows_excluded",
                "severity": "info",
                "title": "Some offer rows lack condition metadata",
                "detail": (
                    f"{unknown_condition_offer_rows} Keepa offer row(s) had missing or unclear condition; they are "
                    "excluded from new-path merchant metrics because KEEPA_ASSUME_UNKNOWN_CONDITION_IS_NEW=false."
                ),
            }
        )
    if no_qualified_buy_box_90d:
        flags.append(
            {
                "code": "no_qualified_buy_box_90d",
                "severity": "critical",
                "title": "No qualified buy-box seller in ~90 days",
                "detail": (
                    "Buy-box history shows essentially no time held by a normal marketplace seller id in the last "
                    "~90 Keepa minutes window — verify listing health before trusting demand."
                ),
            }
        )
    elif no_qualified_buy_box_30d:
        flags.append(
            {
                "code": "no_qualified_buy_box_30d",
                "severity": "warning",
                "title": "Thin buy-box seller presence in ~30 days",
                "detail": (
                    "Very little buy-box time with a qualified seller id in the last ~30 days — confirm competition "
                    "and listing status."
                ),
            }
        )
    if ephemeral_sellers >= 4 and dom_pct is not None and dom_pct >= 75.0:
        flags.append(
            {
                "code": "buy_box_churn_with_dominant_leader",
                "severity": "warning",
                "title": "Many short-lived buy-box sellers",
                "detail": (
                    f"Several sellers held the buy box only briefly (~1–10 days each) in the last year while one "
                    f"seller still shows ~{dom_pct:.0f}% share — review for churn / suppression dynamics."
                ),
            }
        )

    requires_acknowledgement = any(f.get("severity") == "critical" for f in flags) or amazon_only_new_listing

    return {
        "schema_version": "inventory_suggestion_guardrails_v1",
        "status": "complete" if offer_snapshot_complete or pairs else "partial",
        "used_metrics_note": used_metrics_note,
        "offer_snapshot": {
            "offer_rows_total": len(offers),
            "used_like_offer_rows": used_like_offer_rows,
            "unknown_condition_offer_rows": unknown_condition_offer_rows,
            "amazon_new_offer_rows": amazon_new_offer_rows,
            "third_party_new_seller_count": len(third_party_new_seller_ids),
            "buy_box_is_amazon_hint": bool(amazon_bb_hint) if bsl else None,
        },
        "buy_box_recency": {
            "qualified_seller_minutes_buy_box_last_30d": round(mins_30d, 2),
            "third_party_minutes_buy_box_last_30d": tp_minutes_30d,
            "amazon_share_buy_box_last_30d_pct": amz_share_30d,
            "qualified_seller_minutes_buy_box_last_90d": round(mins_90d, 2),
            "qualified_seller_minutes_buy_box_last_365d": round(mins_12m, 2),
            "no_qualified_buy_box_30d": bool(no_qualified_buy_box_30d),
            "no_qualified_buy_box_90d": bool(no_qualified_buy_box_90d),
            "ephemeral_seller_stints_12m_approx": int(ephemeral_sellers),
            "history_pairs_available": len(pairs),
        },
        "flags": flags,
        "amazon_only_new_listing": bool(amazon_only_new_listing),
        "requires_user_acknowledgement": bool(requires_acknowledgement),
        "note": "Heuristic flags from Keepa offers + buyBoxSellerIdHistory — not legal advice; verify Amazon eligibility.",
    }


def build_client_vs_buybox_cohort(
    offers: list[Any] | None,
    buybox_rotation: dict[str, Any],
    buybox_context: dict[str, Any] | None,
    *,
    client_rating_pct: float | None,
    client_review_count: float | None,
) -> dict[str, Any]:
    """
    Per-follower buy-box win %, offer trust signals, distance to client, peer band for planning.
    Win % = Keepa time-on-buy-box in window (not unit sales).
    """
    rot = buybox_rotation if isinstance(buybox_rotation, dict) else {}
    if rot.get("status") != "complete":
        return {
            "status": "partial",
            "note": rot.get("note") or "buy_box_rotation incomplete",
        }
    from unie_cortex.config import settings

    w_rev = float(getattr(settings, "keepa_planning_peer_review_log_weight", 1.0) or 1.0)
    w_rat = float(getattr(settings, "keepa_planning_peer_rating_weight", 1.0) or 1.0)
    eps = float(getattr(settings, "keepa_planning_peer_distance_epsilon", 0.35) or 0.35)

    win_map = {str(k): float(v) for k, v in (rot.get("win_pct_by_seller") or {}).items()}
    dom = str(rot.get("dominant_seller_id") or "")
    follower_ids = {s for s in win_map if _is_real_marketplace_seller(s) and s != dom}
    per = _first_offer_signals_by_seller(offers, follower_ids)

    rows: list[dict[str, Any]] = []
    amazon_offer_rows = 0
    if isinstance(offers, list):
        for o in offers:
            if isinstance(o, dict) and _offer_amazon_flag(o):
                amazon_offer_rows += 1

    bb_ctx = buybox_context if isinstance(buybox_context, dict) else {}
    for sid in sorted(follower_ids):
        sig = per.get(sid) or {}
        pr = sig.get("rating_pct")
        pv = sig.get("review_count")
        row: dict[str, Any] = {
            "seller_id": sid,
            "buy_box_win_pct": win_map.get(sid),
            "rating_pct_from_offers": pr,
            "review_count_from_offers": pv,
            "distance_to_client": None,
            "in_peer_set": False,
            "is_amazon_offer_row": False,
        }
        if isinstance(offers, list):
            for o in offers:
                if isinstance(o, dict) and str(o.get("sellerId") or "").strip() == sid:
                    row["is_amazon_offer_row"] = _offer_amazon_flag(o)
                    break
        rows.append(row)

    peer_avg: float | None = None
    peer_ids: list[str] = []
    planning_note = None

    cr = float(client_rating_pct) if client_rating_pct is not None else None
    cv = float(client_review_count) if client_review_count is not None else None

    if cr is not None and cv is not None and cv >= 0:
        scored: list[tuple[float, str]] = []
        for r in rows:
            pr = r.get("rating_pct_from_offers")
            pv = r.get("review_count_from_offers")
            if pr is None or pv is None:
                continue
            try:
                pvf = float(pv)
                prf = float(pr)
            except (TypeError, ValueError):
                continue
            if pvf < 0:
                continue
            d = _peer_trust_distance(cr, cv, prf, pvf, w_rev=w_rev, w_rat=w_rat)
            r["distance_to_client"] = round(d, 6)
            scored.append((d, str(r["seller_id"])))

        if scored:
            scored.sort(key=lambda x: x[0])
            d_min = scored[0][0]
            peer_ids = [sid for dist, sid in scored if dist <= d_min + eps]
            for r in rows:
                if str(r["seller_id"]) in peer_ids:
                    r["in_peer_set"] = True
            wins = [win_map[s] for s in peer_ids if s in win_map]
            if wins:
                peer_avg = round(sum(wins) / len(wins), 4)
            planning_note = (
                f"Peer band: sellers within distance ≤ {d_min:.4f} + ε({eps}); "
                f"averaged {len(peer_ids)} follower(s) buy-box win %."
            )
    else:
        planning_note = "Provide seller_listing_review_count and rating (or star) to enable peer-distance cohort."

    return {
        "status": "complete",
        "dominant_seller_id": dom,
        "client_rating_pct_used": cr,
        "client_review_count_used": cv,
        "peer_distance_weights": {"review_log": w_rev, "rating_pct_scale": w_rat},
        "peer_distance_epsilon": eps,
        "closest_peer_seller_ids": peer_ids,
        "peer_avg_buy_box_win_pct": peer_avg,
        "peer_count": len(peer_ids),
        "followers": rows,
        "amazon_flagged_offer_rows_in_snapshot": amazon_offer_rows,
        "amazon_retail_strong_hint": str(bb_ctx.get("dominance_hint") or "") == "amazon_or_retail_strong",
        "planning_note": planning_note,
        "note": "Win % is Keepa time-on-buy-box in window, not unit sales share.",
    }


def peer_reference_win_pct_for_planning(
    offers: list[Any] | None,
    buybox_rotation: dict[str, Any],
    *,
    client_rating_pct: float | None,
    client_review_count: float | None,
) -> tuple[float | None, dict[str, Any]]:
    """Mean buy-box win % (0–100) over closest peer sellers, or None to fall back."""
    cohort = build_client_vs_buybox_cohort(
        offers,
        buybox_rotation,
        None,
        client_rating_pct=client_rating_pct,
        client_review_count=client_review_count,
    )
    avg = cohort.get("peer_avg_buy_box_win_pct")
    if isinstance(avg, (int, float)) and avg > 0:
        return float(avg), cohort
    return None, cohort


def _parse_keepa_csv_sections(csv_list: list[int]) -> dict[int, list[int]]:
    """Split Keepa product ``csv`` int array into sections by csv type."""
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


def extract_keepa_monthly_sales_history_6m(
    p: dict[str, Any],
    *,
    seller_monthly_units_mid: float | None = None,
) -> dict[str, Any]:
    """
    Last six calendar months of **relative** sales activity from Keepa sales-rank CSV.

    When ``seller_monthly_units_mid`` is set (seller-scoped planning mid from
    ``apply_seller_scoped_monthly_planning``), bars are scaled so the **average**
    month ≈ that mid (total across six months ≈ ``6 * seller_monthly_units_mid``),
    preserving rank-history **shape** only.

    Without it, scaling matches legacy behavior: total mass equals ``monthlySold``
    when present (visual proxy — not POS truth).
    """
    import math
    from datetime import datetime, timedelta, timezone

    _keepa_epoch = datetime(2011, 1, 1, tzinfo=timezone.utc)

    def _keepa_minute_to_month_key(tm: int) -> str:
        dt = _keepa_epoch + timedelta(minutes=int(tm))
        return f"{dt.year}-{dt.month:02d}"

    ms = _safe_int(p.get("monthlySold"))
    try:
        seller_mid = float(seller_monthly_units_mid) if seller_monthly_units_mid is not None else None
    except (TypeError, ValueError):
        seller_mid = None
    if seller_mid is not None and seller_mid <= 0:
        seller_mid = None

    def _scale_target_total() -> tuple[float, str]:
        """Total units to distribute across the six months (sum of bars)."""
        if seller_mid is not None:
            return 6.0 * seller_mid, "seller_planning_monthly_mid_x6"
        if ms and ms > 0:
            return float(ms), "keepa_monthlySold_total_legacy"
        return 100.0, "placeholder_100"
    csv_list = p.get("csv")
    lu = _safe_int(p.get("lastUpdate"))
    if not isinstance(csv_list, list) or len(csv_list) < 4 or not lu:
        if seller_mid is not None or (ms and ms > 0):
            tgt, scale_basis = _scale_target_total()
            v = round(tgt / 6.0, 2)
            return {
                "status": "approximate",
                "scaling_basis": scale_basis,
                "note": (
                    "Keepa returned no csv/lastUpdate; even placeholder months scaled to seller planning mid (avg ≈ that mid)."
                    if seller_mid is not None
                    else "Keepa returned no csv/lastUpdate; bars split current monthlySold evenly (legacy placeholder)."
                ),
                "six_month_mean_units": v,
                "months": [{"month_key": f"M{i + 1}", "units_est": v} for i in range(6)],
            }
        return {"status": "partial", "note": "No Keepa csv or monthlySold for six-month chart."}

    try:
        as_ints = [int(x) for x in csv_list]
    except (TypeError, ValueError):
        as_ints = []

    sections = _parse_keepa_csv_sections(as_ints)
    # 3 = SALES_RANK in Keepa product csv types (US marketplace)
    rank_chunk = sections.get(3) or []
    if len(rank_chunk) < 4:
        if seller_mid is not None or (ms and ms > 0):
            tgt, scale_basis = _scale_target_total()
            v = round(tgt / 6.0, 2)
            return {
                "status": "approximate",
                "scaling_basis": scale_basis,
                "note": (
                    "No sales-rank history section; even split scaled to seller planning mid."
                    if seller_mid is not None
                    else "No sales-rank history section; bars split monthlySold evenly."
                ),
                "six_month_mean_units": v,
                "months": [{"month_key": f"M{i + 1}", "units_est": v} for i in range(6)],
            }
        return {"status": "partial", "note": "Could not read rank history from csv."}

    pairs: list[tuple[int, int]] = []
    for j in range(0, len(rank_chunk) - 1, 2):
        try:
            t = int(rank_chunk[j])
            rnk = int(rank_chunk[j + 1])
        except (TypeError, ValueError):
            continue
        if rnk > 0:
            pairs.append((t, rnk))
    if len(pairs) < 2:
        if seller_mid is not None or (ms and ms > 0):
            tgt, scale_basis = _scale_target_total()
            v = round(tgt / 6.0, 2)
            return {
                "status": "approximate",
                "scaling_basis": scale_basis,
                "note": (
                    "Rank series too short; even split scaled to seller planning mid."
                    if seller_mid is not None
                    else "Rank series too short; using monthlySold split."
                ),
                "six_month_mean_units": v,
                "months": [{"month_key": f"M{i + 1}", "units_est": v} for i in range(6)],
            }
        return {"status": "partial", "note": "Insufficient rank points."}

    keepa_minutes_per_month = 30 * 1440
    t_end = int(lu)
    t_start = t_end - 6 * keepa_minutes_per_month
    buckets: dict[str, list[int]] = {}
    for t, rnk in pairs:
        if t < t_start or t > t_end:
            continue
        mk = _keepa_minute_to_month_key(t)
        buckets.setdefault(mk, []).append(rnk)

    month_keys = sorted(buckets.keys())[-6:]
    if len(month_keys) < 6:
        pad = 6 - len(month_keys)
        if month_keys:
            first = month_keys[0]
            month_keys = [first] * pad + month_keys
        else:
            mk0 = _keepa_minute_to_month_key(t_end)
            month_keys = [mk0] * 6

    activities: list[float] = []
    out_months: list[dict[str, Any]] = []
    for mk in month_keys[-6:]:
        ranks = buckets.get(mk) or []
        if ranks:
            mr = sum(ranks) / len(ranks)
            act = 1.0 / math.log10(mr + 10.0)
        else:
            act = 0.01
        activities.append(act)
        out_months.append({"month_key": mk, "activity_raw": round(act, 6), "units_est": 0.0})

    total_act = sum(activities) or 1.0
    target_total, scale_basis = _scale_target_total()
    for i, m in enumerate(out_months):
        m["units_est"] = round(target_total * activities[i] / total_act, 2)

    mean_u = round(sum(m["units_est"] for m in out_months) / max(len(out_months), 1), 2)
    seller_scaled = seller_mid is not None
    return {
        "status": "complete",
        "scaling_basis": scale_basis,
        "basis": (
            "keepa_sales_rank_csv_proxy_scaled_to_seller_planning_mid"
            if seller_scaled
            else "keepa_sales_rank_csv_proxy_scaled_to_monthlySold"
        ),
        "note": (
            "Rank-shaped months scaled so average ≈ seller-scoped planning mid (not raw ASIN monthlySold)."
            if seller_scaled
            else "Bars are rank-activity shares scaled to Keepa monthlySold (legacy marketplace total-mass)."
        ),
        "six_month_mean_units": mean_u,
        "months": out_months,
    }


def _keepa_csv_pairs_for_type(p: dict[str, Any], csv_type: int) -> list[tuple[int, int]]:
    csv_list = p.get("csv")
    if not isinstance(csv_list, list):
        return []
    try:
        as_ints = [int(x) for x in csv_list]
    except (TypeError, ValueError):
        return []
    sections = _parse_keepa_csv_sections(as_ints)
    chunk = sections.get(csv_type) or []
    out: list[tuple[int, int]] = []
    for j in range(0, len(chunk) - 1, 2):
        try:
            t = int(chunk[j])
            v = int(chunk[j + 1])
        except (TypeError, ValueError):
            continue
        out.append((t, v))
    out.sort(key=lambda x: x[0])
    return out


def _downsample_pairs(pairs: list[tuple[int, int]], max_pts: int) -> list[tuple[int, int]]:
    if len(pairs) <= max_pts:
        return pairs
    n = len(pairs)
    idxs = [int(round(i * (n - 1) / (max_pts - 1))) for i in range(max_pts)]
    return [pairs[j] for j in idxs]


def build_keepa_trend_bundle(
    p: dict[str, Any],
    *,
    plan_mid: float | None,
    plan_low: float | None,
    plan_high: float | None,
    target_days_cover: float = 30.0,
) -> dict[str, Any]:
    """
    Compact CPU-derived trend narrative + downsampled csv series for UI (not full Keepa csv arrays).
    """
    from unie_cortex.config import settings as _ts

    max_pts = int(getattr(_ts, "keepa_trend_bundle_max_points", 160) or 160)
    risk_disc = float(getattr(_ts, "keepa_trend_risk_discount", 1.0) or 1.0)

    lu = _safe_int(p.get("lastUpdate")) or 0
    rank_pairs_all = [(t, v) for t, v in _keepa_csv_pairs_for_type(p, 3) if v > 0]
    bb_raw = _keepa_csv_pairs_for_type(p, _KEEPA_CSV_BUY_BOX_SHIPPING)
    new_pairs = _keepa_csv_pairs_for_type(p, _KEEPA_CSV_NEW)
    amz_pairs = _keepa_csv_pairs_for_type(p, _KEEPA_CSV_AMAZON)

    drivers: list[dict[str, Any]] = []
    score = 0
    win30 = 30 * 1440
    win90 = 90 * 1440

    if rank_pairs_all and lu > 0:
        t_cut = lu - win30
        older = [r for t, r in rank_pairs_all if t < t_cut]
        recent = [r for t, r in rank_pairs_all if t >= t_cut]
        if older and recent:
            med_o = sorted(older)[len(older) // 2]
            med_r = sorted(recent)[len(recent) // 2]
            delta = med_r - med_o
            if delta < 0:
                score += 1
                drivers.append(
                    {
                        "label": "BSR (30d)",
                        "delta": int(delta),
                        "snippet": "Median sales rank improved vs prior window (lower is better).",
                    }
                )
            elif delta > max(500, int(med_o * 0.05)):
                score -= 1
                drivers.append(
                    {
                        "label": "BSR (30d)",
                        "delta": int(delta),
                        "snippet": "Median sales rank softened vs prior window.",
                    }
                )
            else:
                drivers.append(
                    {
                        "label": "BSR (30d)",
                        "delta": int(delta),
                        "snippet": "Sales rank roughly stable vs prior 30d chunk.",
                    }
                )

    if bb_raw and lu > 0:
        vals: list[float] = []
        for t, cents in bb_raw:
            if lu - win90 <= t <= lu and cents > 0:
                u = _keepa_cents_to_usd(cents)
                if u is not None:
                    vals.append(u)
        if len(vals) >= 3:
            lo, hi = min(vals), max(vals)
            mean_v = sum(vals) / len(vals)
            spread = (hi - lo) / mean_v if mean_v > 0 else 0.0
            if spread > 0.12:
                score -= 1
                drivers.append(
                    {
                        "label": "Buy-box landed",
                        "delta_numeric": round(spread, 4),
                        "snippet": "Landed buy-box levels varied notably in ~90d (pricing pressure or churn).",
                    }
                )
            else:
                score += 1
                drivers.append(
                    {
                        "label": "Buy-box landed",
                        "delta_numeric": round(spread, 4),
                        "snippet": "Buy-box landed relatively tight over ~90d.",
                    }
                )

    if amz_pairs and lu > 0:
        win = [(t, v) for t, v in amz_pairs if lu - win90 <= t <= lu]
        if len(win) > 5:
            pos = sum(1 for _, v in win if v > 0)
            ratio = pos / len(win)
            if ratio >= 0.85:
                score += 1
                drivers.append(
                    {
                        "label": "Amazon price (csv)",
                        "delta_numeric": round(ratio, 3),
                        "snippet": "Amazon price points mostly present in recent csv window (in-stock proxy).",
                    }
                )
            elif ratio < 0.5:
                score -= 1
                drivers.append(
                    {
                        "label": "Amazon price (csv)",
                        "delta_numeric": round(ratio, 3),
                        "snippet": "Gaps in Amazon price signal in recent csv — verify retail presence.",
                    }
                )

    if new_pairs and lu > 0:
        half = win90 // 2
        early = [v for t, v in new_pairs if lu - win90 <= t < lu - half]
        late = [v for t, v in new_pairs if lu - half <= t <= lu]
        if early and late:
            e_med = sorted(early)[len(early) // 2]
            l_med = sorted(late)[len(late) // 2]
            if l_med > e_med * 1.15:
                score -= 1
                drivers.append(
                    {
                        "label": "New-offer count (csv)",
                        "delta": int(l_med - e_med),
                        "snippet": "New-offer count trended up late in the window.",
                    }
                )
            elif l_med < e_med * 0.85:
                score += 1
                drivers.append(
                    {
                        "label": "New-offer count (csv)",
                        "delta": int(l_med - e_med),
                        "snippet": "New-offer count eased late in the window.",
                    }
                )

    if score >= 1:
        verdict = "favorable"
    elif score <= -1:
        verdict = "cautious"
    else:
        verdict = "neutral"

    forecast_band: dict[str, Any] | None = None
    suggested_cover_units: int | None = None
    if plan_mid is not None and float(plan_mid) > 0:
        pm = float(plan_mid)
        plf = float(plan_low) if plan_low is not None and float(plan_low) > 0 else round(pm * 0.85, 2)
        phf = float(plan_high) if plan_high is not None and float(plan_high) > 0 else round(pm * 1.15, 2)
        forecast_band = {
            "low": plf,
            "mid": round(pm, 2),
            "high": phf,
            "assumptions": [
                "Anchored to seller planning monthly mid from Keepa extract (not POS truth).",
                "Band width reflects listing + buy-box uncertainty.",
            ],
        }
        cover = max(1.0, float(target_days_cover))
        suggested_cover_units = int(round(pm * (cover / 30.0) * risk_disc))

    chart_series: list[dict[str, Any]] = []
    if rank_pairs_all:
        ds = _downsample_pairs(rank_pairs_all, max_pts)

        def _nearest_bb_usd(t: int) -> float | None:
            best: tuple[int, float] | None = None
            for tt, cents in bb_raw:
                if cents <= 0:
                    continue
                u = _keepa_cents_to_usd(cents)
                if u is None:
                    continue
                d = abs(tt - t)
                if d > 10 * 1440:
                    continue
                if best is None or d < best[0]:
                    best = (d, u)
            return best[1] if best else None

        def _nearest_new_count(t: int) -> int | None:
            if not new_pairs:
                return None
            best: tuple[int, int] | None = None
            for tt, vv in new_pairs:
                d = abs(tt - t)
                if d > 10 * 1440:
                    continue
                if best is None or d < best[0]:
                    best = (d, vv)
            return best[1] if best and best[1] >= 0 else None

        for t, rnk in ds:
            chart_series.append(
                {
                    "t": t,
                    "sales_rank": rnk,
                    "buy_box_landed_usd": _nearest_bb_usd(t),
                    "new_offer_count": _nearest_new_count(t),
                }
            )

    status = "complete" if chart_series or drivers else "partial"
    return {
        "bundle_version": KEEPA_TREND_BUNDLE_VERSION,
        "status": status,
        "last_update_minute": lu or None,
        "verdict": verdict,
        "drivers": drivers,
        "forecast_band_monthly_units": forecast_band,
        "suggested_cover_units": suggested_cover_units,
        "cover_days_used": float(target_days_cover),
        "risk_discount_applied": round(risk_disc, 4),
        "chart": {
            "max_points": max_pts,
            "series": chart_series,
            "series_note": "Downsampled Keepa csv (rank type 3; buy box 18; new count 1 when present).",
        },
    }


def _cohort_signals_from_offers(offers: list[Any], seller_ids: set[str]) -> dict[str, Any]:
    """First live row per seller id: FBA flag and best-effort rating / review fields."""
    per_sid: dict[str, dict[str, Any]] = {}
    for o in offers:
        if not isinstance(o, dict):
            continue
        raw = o.get("sellerId")
        if raw is None:
            continue
        sid = str(raw).strip()
        if sid not in seller_ids or sid in per_sid:
            continue
        fba = o.get("isFBA")
        if fba is None:
            fba = o.get("fba")
        is_fba = fba in (True, 1, "1", "true", "True")
        rating = None
        for k in (
            "recentStarRating",
            "recentRating",
            "sellerRating",
            "rating",
            "sellerPositiveRating",
        ):
            if k in o and o.get(k) is not None:
                rating = _norm_listing_rating_to_pct(o.get(k))
                break
        reviews = None
        for k in ("recentReviewCount", "reviewCount", "reviewsTotal", "sellerReviewCount"):
            if k in o and o.get(k) is not None:
                try:
                    reviews = float(o.get(k))
                except (TypeError, ValueError):
                    reviews = None
                break
        per_sid[sid] = {"is_fba": is_fba, "rating_pct": rating, "review_count": reviews}
    ratings = [x["rating_pct"] for x in per_sid.values() if x.get("rating_pct") is not None]
    revs = [x["review_count"] for x in per_sid.values() if x.get("review_count") is not None]
    fba_ct = sum(1 for x in per_sid.values() if x.get("is_fba"))
    n = len(per_sid)
    return {
        "sellers_observed": n,
        "avg_rating_pct": round(sum(ratings) / len(ratings), 2) if ratings else None,
        "avg_review_count": round(sum(revs) / len(revs), 2) if revs else None,
        "fba_share_among_sellers": round(fba_ct / n, 4) if n else None,
    }


def _follower_similarity_multiplier(
    cohort: dict[str, Any],
    *,
    client_rating_pct: float | None,
    client_reviews: float | None,
    client_is_fba: bool | None,
    weight: float,
) -> tuple[float, dict[str, Any]]:
    if weight <= 0:
        return 1.0, {"note": "similarity weight 0 — disabled"}
    has_client = (
        client_rating_pct is not None or client_reviews is not None or client_is_fba is not None
    )
    if not has_client:
        return 1.0, {"note": "no client listing signals — multiplier 1"}

    parts: list[float] = []
    cr = cohort.get("avg_rating_pct")
    if cr is not None and client_rating_pct is not None:
        parts.append(max(0.45, 1.0 - abs(float(client_rating_pct) - float(cr)) / 45.0))
    cv = cohort.get("avg_review_count")
    if cv is not None and client_reviews is not None and cv > 0:
        parts.append(min(1.25, max(0.35, (float(client_reviews) / float(cv)) ** 0.5)))

    sim = sum(parts) / len(parts) if parts else 1.0
    fba_frac = cohort.get("fba_share_among_sellers")
    if client_is_fba is False and fba_frac is not None and float(fba_frac) >= 0.6:
        sim *= 0.9
    elif client_is_fba is True and fba_frac is not None and float(fba_frac) >= 0.5:
        sim = min(1.15, sim * 1.05)

    mult = 1.0 + weight * (sim - 1.0)
    mult = max(0.82, min(1.22, mult))
    return mult, {"cohort": cohort, "similarity_parts_used": len(parts), "raw_sim": round(sim, 4)}


def extract_buybox_rotation_profile(
    p: dict[str, Any],
    *,
    window_days: float | None = None,
) -> dict[str, Any]:
    """
    Buy box **time-on-box** shares from ``buyBoxSellerIdHistory`` (requires Keepa ``offers`` > 0 on the request).

    Dominant seller = highest share among real seller ids (excludes ``-1`` / ``-2`` sentinels).
    ``follower_avg_win_pct`` = mean of **each other** real seller's win % (matches "2nd through last" in the UI).
    """
    from unie_cortex.config import settings

    wd = float(window_days if window_days is not None else settings.keepa_buybox_history_window_days)
    window_mins = int(max(1.0, wd) * 24 * 60)
    pairs = _parse_buybox_seller_id_history(p.get("buyBoxSellerIdHistory"))
    if len(pairs) < 2:
        return {
            "status": "partial",
            "note": (
                "buyBoxSellerIdHistory missing or too short — use Keepa product with stats>0 and offers>=20 "
                "(offers also enables buy box history)."
            ),
        }

    lu = _safe_int(p.get("lastUpdate"))
    t_end = int(lu) if lu and lu > 0 else pairs[-1][0]
    dur, total = _buybox_window_durations(pairs, t_end, window_mins)
    if total <= 0:
        return {"status": "partial", "note": "no buy box time in Keepa history window"}

    pct_by_sid: dict[str, float] = {k: round(100.0 * v / total, 4) for k, v in dur.items()}
    real = [(s, pct_by_sid[s]) for s in pct_by_sid if _is_real_marketplace_seller(s)]
    if len(real) < 2:
        return {
            "status": "partial",
            "note": "need ≥2 real sellers in window for follower-average model",
            "win_pct_by_seller_all": pct_by_sid,
        }

    real.sort(key=lambda x: (-x[1], x[0]))
    dominant_sid, dominant_pct = real[0]
    followers = real[1:]
    follower_avg = sum(f[1] for f in followers) / len(followers)

    return {
        "status": "complete",
        "window_days_used": round(wd, 4),
        "window_keepa_minutes": window_mins,
        "t_end_keepa_minute": t_end,
        "dominant_seller_id": dominant_sid,
        "dominant_win_pct": dominant_pct,
        "follower_seller_count": len(followers),
        "follower_avg_win_pct": round(follower_avg, 4),
        "win_pct_by_seller": {k: v for k, v in real},
        "win_pct_by_seller_all": pct_by_sid,
    }


def build_buybox_window_analysis(
    p: dict[str, Any],
    *,
    decision_window_days: float = 30.0,
) -> dict[str, Any]:
    """
    Windowed buy-box context for decisioning (30d) with expanded context (90d/365d).

    Uses Keepa ``buyBoxSellerIdHistory`` durations only; this is independent from offer snapshot counts.
    """
    pairs = _parse_buybox_seller_id_history(p.get("buyBoxSellerIdHistory"))
    if len(pairs) < 2:
        return {
            "status": "partial",
            "note": "buyBoxSellerIdHistory missing or too short for 30/90/365 analysis",
            "decision_window_days": float(decision_window_days),
            "windows": [],
            "by_window_days": {},
        }
    lu = _safe_int(p.get("lastUpdate"))
    t_end = int(lu) if lu and lu > 0 else pairs[-1][0]
    if t_end <= 0:
        return {
            "status": "partial",
            "note": "invalid Keepa lastUpdate for buy-box window analysis",
            "decision_window_days": float(decision_window_days),
            "windows": [],
            "by_window_days": {},
        }

    windows_out: list[dict[str, Any]] = []
    by_window: dict[str, Any] = {}
    for wd in (30.0, 90.0, 365.0):
        mins = int(max(1.0, float(wd)) * 24 * 60)
        dur, total = _buybox_window_durations(pairs, t_end, mins)
        real_dur = {sid: m for sid, m in dur.items() if _is_real_marketplace_seller(str(sid))}
        qualified = float(sum(real_dur.values()))
        amz_sid = "ATVPDKIKX0DER"
        amz_min = float(real_dur.get(amz_sid, 0.0))
        tp_min = max(0.0, qualified - amz_min)
        amz_share = (100.0 * amz_min / qualified) if qualified > 0 else 0.0
        tp_share = (100.0 * tp_min / qualified) if qualified > 0 else 0.0
        top = sorted(real_dur.items(), key=lambda x: (-x[1], x[0]))[:8]
        row = {
            "window_days": int(wd),
            "window_keepa_minutes": mins,
            "qualified_seller_minutes": round(qualified, 2),
            "distinct_real_sellers": len(real_dur),
            "amazon_minutes": round(amz_min, 2),
            "third_party_minutes": round(tp_min, 2),
            "amazon_share_pct": round(amz_share, 4),
            "third_party_share_pct": round(tp_share, 4),
            "top_sellers_by_minutes": [
                {"seller_id": sid, "minutes": round(float(m), 2), "share_pct": round(100.0 * float(m) / qualified, 4)}
                for sid, m in top
            ]
            if qualified > 0
            else [],
        }
        windows_out.append(row)
        by_window[str(int(wd))] = row
    return {
        "status": "complete",
        "decision_window_days": float(decision_window_days),
        "t_end_keepa_minute": int(t_end),
        "windows": windows_out,
        "by_window_days": by_window,
        "note": "Decisioning should use 30d; 90d/365d are context only.",
    }


def _planning_slice_no_seller_id(M: float, raw_slice: float, large_threshold: float, cap_3p: float) -> float:
    """Large ASIN velocity → strict slice + cap; small velocity → floor at 25% so tiny listings are not 3 units/mo."""
    if M >= large_threshold:
        return min(raw_slice, cap_3p)
    return min(max(raw_slice, M * 0.25), cap_3p)


def apply_seller_scoped_monthly_planning(
    M: float,
    low: float,
    high: float,
    *,
    product: dict[str, Any] | None = None,
    competition_level: str,
    buy_box_seller_id: str | None,
    marketplace_seller_id: str | None,
    seller_landscape: dict[str, Any],
    buybox_rotation: dict[str, Any] | None = None,
    offers: list[Any] | None = None,
    seller_listing_profile: dict[str, Any] | None = None,
) -> tuple[float, float, float, dict[str, Any]]:
    """
    ``M`` = marketplace monthly mid **after category adjustment** (still ASIN-level).

    When Keepa returns ``buyBoxSellerIdHistory`` (via ``offers`` on the product request), we prefer
    **time-on-buy-box shares**: entrant default = marketplace velocity × mean win-% of non-dominant
    sellers; known ``marketplace_seller_id`` uses that seller's observed share. Otherwise fall back
    to competition-tier slices.
    """
    from unie_cortex.config import settings

    cap_3p = float(getattr(settings, "keepa_planning_monthly_cap_3p", 400) or 400)
    large_th = float(getattr(settings, "keepa_planning_large_velocity_threshold", 800) or 800)
    cap_bb = float(getattr(settings, "keepa_planning_buybox_winner_cap", 1200) or 1200)
    cap_hist = float(getattr(settings, "keepa_planning_buybox_history_known_cap", 50_000) or 50_000)
    sim_w = float(getattr(settings, "keepa_planning_buybox_follower_similarity_weight", 0) or 0)

    comp = (competition_level or "unknown").lower()
    frac = {"high": 0.012, "medium": 0.022, "low": 0.045, "unknown": 0.028}.get(comp, 0.028)
    reasons: list[str] = []
    planning_mode = "competition_tier_slice"
    hist_rate: float | None = None
    similarity_detail: dict[str, Any] = {}

    sid = (marketplace_seller_id or "").strip() or None
    bb = (str(buy_box_seller_id).strip() if buy_box_seller_id else None) or None
    prof = seller_listing_profile or {}
    client_r = prof.get("listing_rating_12m_pct")
    client_rev = prof.get("listing_review_count")
    client_fba = prof.get("listing_is_fba")
    try:
        client_r_f = float(client_r) if client_r is not None else None
    except (TypeError, ValueError):
        client_r_f = None
    try:
        client_rev_f = float(client_rev) if client_rev is not None else None
    except (TypeError, ValueError):
        client_rev_f = None
    if client_fba is not None and not isinstance(client_fba, bool):
        client_fba = bool(client_fba)

    rot = buybox_rotation if (buybox_rotation or {}).get("status") == "complete" else None
    if rot:
        win_map = {str(k): float(v) for k, v in (rot.get("win_pct_by_seller") or {}).items()}
        dom_sid = str(rot.get("dominant_seller_id") or "")
        fol_avg_pct = float(rot.get("follower_avg_win_pct") or 0.0)
        follower_ids = {s for s in win_map if s != dom_sid and _is_real_marketplace_seller(s)}
        cohort: dict[str, Any] = {}
        sim_mult = 1.0
        if offers and follower_ids and sim_w > 0:
            cohort = _cohort_signals_from_offers(list(offers), follower_ids)
            sim_mult, similarity_detail = _follower_similarity_multiplier(
                cohort,
                client_rating_pct=client_r_f,
                client_reviews=client_rev_f,
                client_is_fba=client_fba,
                weight=sim_w,
            )

        if sid and sid in win_map:
            hist_rate = win_map[sid] / 100.0
            plan = min(M * hist_rate, cap_hist)
            planning_mode = "buybox_history_seller_share"
            reasons.append(
                "Used Keepa buyBoxSellerIdHistory win-% for this seller × ASIN monthly velocity "
                f"(capped at keepa_planning_buybox_history_known_cap={int(cap_hist)})."
            )
        else:
            peer_pct: float | None = None
            peer_detail: dict[str, Any] = {}
            if (
                client_r_f is not None
                and client_rev_f is not None
                and client_rev_f >= 0
                and offers
            ):
                peer_pct, peer_detail = peer_reference_win_pct_for_planning(
                    list(offers),
                    rot,
                    client_rating_pct=client_r_f,
                    client_review_count=client_rev_f,
                )
            if peer_pct is not None and peer_pct > 0:
                hist_rate = peer_pct / 100.0
                plan = min(M * hist_rate, cap_3p)
                planning_mode = "buybox_history_peer_cohort"
                reasons.append(
                    "Planning = monthly velocity × **peer-matched** buy-box win % "
                    "(closest followers by review count + rating vs your store; ties averaged)."
                )
                similarity_detail = {**similarity_detail, "peer_cohort": peer_detail}
            else:
                hist_rate = fol_avg_pct / 100.0
                plan = M * hist_rate * sim_mult
                plan = min(max(0.0, plan), cap_3p)
                planning_mode = "buybox_history_follower_avg"
                reasons.append(
                    "No seller id (or seller not in history): planning = monthly velocity × **average** win-% "
                    "of non-dominant sellers in Keepa buy box history (entrant benchmark)."
                )
                if peer_detail:
                    similarity_detail = {**similarity_detail, "peer_cohort": peer_detail}
                if sim_mult != 1.0:
                    reasons.append(
                        f"Adjusted ×{round(sim_mult, 4)} from optional client vs follower-offer cohort signals."
                    )

    elif sid and bb and sid == bb:
        plan = min(M * 0.42, cap_bb)
        planning_mode = "buybox_current_match_heuristic"
        reasons.append(
            "marketplace_seller_id matches current Keepa buy_box_seller_id — heuristic slice (no history)."
        )
    elif sid and seller_landscape.get("status") == "complete":
        share = None
        for row in seller_landscape.get("seller_row_share_top") or []:
            if str(row.get("seller_id")) == sid:
                share = float(row.get("row_share") or 0)
                break
        if share is not None and share > 0:
            eff = max(share, 0.015)
            plan = min(M * eff, min(cap_bb, 1500.0))
            planning_mode = "offer_row_share"
            reasons.append(
                f"Scaled by your seller's **offer-row** share (~{share:.1%}) in this snapshot — not % of sales."
            )
        else:
            raw = M * frac
            plan = _planning_slice_no_seller_id(M, raw, large_th, cap_3p)
            reasons.append("Seller id provided but no matching offer rows — conservative marketplace slice + cap.")
    else:
        raw = M * frac
        plan = _planning_slice_no_seller_id(M, raw, large_th, cap_3p)
        reasons.append(
            "No buy box history and no seller match: Keepa monthlySold is **whole-listing** velocity; "
            "planning uses buy-box competition tier × slice + cap (see keepa_planning_* settings)."
        )

    # Hard guardrail: if last 30d buy-box is effectively Amazon-only, zero 3P planning by default.
    bba = build_buybox_window_analysis(product or {}) if isinstance(product, dict) else {}
    by30 = (bba.get("by_window_days") or {}).get("30") if isinstance(bba, dict) else None
    amz_30 = float(by30.get("amazon_share_pct") or 0.0) if isinstance(by30, dict) else 0.0
    tp_30 = float(by30.get("third_party_minutes") or 0.0) if isinstance(by30, dict) else 0.0
    if amz_30 >= 95.0 and tp_30 <= 0.0 and not sid:
        plan = 0.0
        planning_mode = "amazon_buybox_30d_only_guardrail"
        reasons.append(
            "Last 30d buy-box history is effectively Amazon-only (>=95% and no 3P minutes); "
            "default 3P planning is clamped to 0 for safety."
        )

    plan = max(0.0, float(plan))
    ratio = plan / M if M > 0 else 1.0
    pl = max(0.5, round(low * ratio, 2))
    ph = max(pl, round(high * ratio, 2))
    meta: dict[str, Any] = {
        "marketplace_monthly_mid_after_category": round(M, 2),
        "planning_monthly_units_mid": round(plan, 2),
        "planning_share_of_marketplace_mid_est": round(ratio, 6),
        "planning_mode": planning_mode,
        "competition_level_used": comp,
        "slice_fraction_used": frac,
        "buybox_history_rate": round(hist_rate, 6) if hist_rate is not None else None,
        "buybox_window_analysis": bba if isinstance(bba, dict) else None,
        "caps": {
            "planning_cap_3p": cap_3p,
            "planning_cap_buybox_match": cap_bb,
            "planning_cap_buybox_history_known": cap_hist,
        },
        "similarity": similarity_detail,
        "reasoning": reasons,
    }
    return round(plan, 2), pl, ph, meta


def _apply_category_monthly(mid: float, low: float, high: float, factor: float) -> tuple[float, float, float, dict[str, Any]]:
    damped = 1.0 + (factor - 1.0) * 0.4
    return (
        round(mid * damped, 2),
        round(low * damped, 2),
        round(high * damped, 2),
        {"category_velocity_factor": factor, "damped_multiplier": round(damped, 4), "basis": "monthlySold"},
    )


def _apply_category_rank(mid: float, low: float, high: float, factor: float) -> tuple[float, float, float, dict[str, Any]]:
    mid_adj = round(mid * factor, 2)
    scale = mid_adj / mid if mid > 0 else 1.0
    return (
        mid_adj,
        round(low * scale, 2),
        round(high * scale, 2),
        {"category_velocity_factor": factor, "basis": "salesRank_heuristic"},
    )


def _first_offer_signals_by_seller(offers: list[Any] | None, seller_ids: set[str]) -> dict[str, dict[str, Any]]:
    per: dict[str, dict[str, Any]] = {}
    if not isinstance(offers, list):
        return per
    for o in offers:
        if not isinstance(o, dict):
            continue
        raw = o.get("sellerId")
        if raw is None:
            continue
        sid = str(raw).strip()
        if sid not in seller_ids or sid in per:
            continue
        rating = None
        for k in (
            "recentStarRating",
            "recentRating",
            "sellerRating",
            "rating",
            "sellerPositiveRating",
        ):
            if k in o and o.get(k) is not None:
                rating = _norm_listing_rating_to_pct(o.get(k))
                break
        reviews = None
        for k in ("recentReviewCount", "reviewCount", "reviewsTotal", "sellerReviewCount"):
            if k in o and o.get(k) is not None:
                try:
                    reviews = float(o.get(k))
                except (TypeError, ValueError):
                    reviews = None
                break
        per[sid] = {"rating_pct": rating, "review_count": reviews}
    return per


def build_buy_box_market_summary(
    *,
    method: str | None,
    buybox_rotation: dict[str, Any],
    seller_landscape: dict[str, Any],
    buybox_context: dict[str, Any] | None = None,
    buybox_stats_light: dict[str, Any] | None = None,
) -> dict[str, Any]:
    monthly_basis = (
        "monthlySold"
        if method == "keepa_monthlySold"
        else ("salesRank_heuristic" if method == "keepa_salesRank_heuristic" else "none")
    )
    rot = buybox_rotation if isinstance(buybox_rotation, dict) else {}
    land = seller_landscape if isinstance(seller_landscape, dict) else {}
    bb = buybox_context if isinstance(buybox_context, dict) else {}
    bsl = buybox_stats_light if isinstance(buybox_stats_light, dict) else {}
    amz_rows = int(bb.get("amazon_flagged_offer_rows") or 0)
    amz_merch = bb.get("amazon_merchants_in_snapshot")
    try:
        amz_merch_n = int(amz_merch) if amz_merch is not None else None
    except (TypeError, ValueError):
        amz_merch_n = None
    ocr = bb.get("offer_row_count")
    if ocr is None:
        ocr = bb.get("offer_rows_available")
    try:
        ocr_n = int(ocr) if ocr is not None else None
    except (TypeError, ValueError):
        ocr_n = None
    u_all = bb.get("unique_merchants_all_conditions")
    if u_all is None:
        u_all = land.get("unique_merchants_all_conditions")
    u_new = bb.get("unique_merchants_new_only")
    if u_new is None:
        u_new = land.get("unique_merchants_new_only")
    try:
        u_all_n = int(u_all) if u_all is not None else None
    except (TypeError, ValueError):
        u_all_n = None
    try:
        u_new_n = int(u_new) if u_new is not None else None
    except (TypeError, ValueError):
        u_new_n = None
    out: dict[str, Any] = {
        "monthly_sales_basis": monthly_basis,
        "rotation_status": rot.get("status"),
        "seller_landscape_status": land.get("status"),
        "amazon_retail_offer_rows": amz_rows,
        "amazon_retail_offer_presence": amz_rows > 0,
        "amazon_merchants_in_snapshot": amz_merch_n,
        "buy_box_is_amazon_hint": bsl.get("buyBoxIsAmazon"),
        "amazon_or_retail_strong_hint": str(bb.get("dominance_hint") or "") == "amazon_or_retail_strong",
        "offer_row_count": ocr_n,
        "unique_merchants_all_conditions": u_all_n,
        "unique_merchants_new_only": u_new_n,
        "metric_definitions": {
            "distinct_buy_box_sellers_in_window": (
                "Count of real marketplace seller IDs with any buy-box time in Keepa buyBoxSellerIdHistory "
                "for the configured window — not the same as offer-row count."
            ),
            "offer_row_count": "Total Keepa offer[] lines in the snapshot (FBA variants, warehouses, price points).",
            "unique_merchants_all_conditions": "Distinct sellerId values with at least one offer row (any condition).",
            "unique_merchants_new_only": (
                "Distinct sellerIds with at least one row on the new listing path (see condition policy / digest)."
            ),
            "offer_snapshot_unique_sellers": "Distinct sellerIds among rows used for row-share (those with sellerId).",
        },
    }
    if rot.get("status") == "complete":
        win_map = rot.get("win_pct_by_seller") or {}
        real_ids = [s for s in win_map if _is_real_marketplace_seller(str(s))]
        out["distinct_buy_box_sellers_in_window"] = len(real_ids)
        out["dominant_seller_id"] = rot.get("dominant_seller_id")
        out["dominant_win_pct"] = rot.get("dominant_win_pct")
        out["follower_avg_win_pct"] = rot.get("follower_avg_win_pct")
    else:
        out["distinct_buy_box_sellers_in_window"] = None
        out["dominant_seller_id"] = rot.get("dominant_seller_id")
        out["dominant_win_pct"] = None
        out["follower_avg_win_pct"] = None
    if land.get("status") == "complete":
        out["offer_snapshot_unique_sellers"] = land.get("unique_sellers_in_snapshot")
        out["offer_rows_counted"] = land.get("offer_rows_counted")
        if out.get("offer_row_count") is None and land.get("digest_offer_row_count_total") is not None:
            try:
                out["offer_row_count"] = int(land.get("digest_offer_row_count_total") or 0)
            except (TypeError, ValueError):
                pass
    else:
        out["offer_snapshot_unique_sellers"] = None
        out["offer_rows_counted"] = None
    out["note"] = (
        "distinct_buy_box_sellers_in_window = buy-box history (time-on-box). "
        "offer_row_count / offer_rows_counted = Keepa offer lines. "
        "unique_merchants_* = grouped by sellerId (digest)."
    )
    return out


def build_similar_seller_buybox_metrics(
    offers: list[Any] | None,
    buybox_rotation: dict[str, Any],
    *,
    client_rating_pct: float | None,
    client_review_count: float | None,
) -> dict[str, Any]:
    rot = buybox_rotation if isinstance(buybox_rotation, dict) else {}
    if rot.get("status") != "complete":
        return {
            "status": "partial",
            "note": "complete buy_box_rotation required for similar-seller buy-box metrics",
        }
    win_map_raw = rot.get("win_pct_by_seller") or {}
    win_map = {str(k): float(v) for k, v in win_map_raw.items()}
    dom = str(rot.get("dominant_seller_id") or "")
    follower_ids = {s for s in win_map if _is_real_marketplace_seller(s) and s != dom}
    if not follower_ids:
        return {"status": "partial", "note": "no follower sellers in rotation window"}

    per = _first_offer_signals_by_seller(offers, follower_ids)
    cohort_note: str | None = None
    if client_rating_pct is None and client_review_count is None:
        similar_ids: set[str] = set(follower_ids)
        cohort_note = "no client listing signals — all followers treated as peer cohort"
    else:
        similar_ids = set()
        for sid in follower_ids:
            sig = per.get(sid) or {}
            r = sig.get("rating_pct")
            rev = sig.get("review_count")
            ok = True
            if client_rating_pct is not None and r is not None:
                if abs(float(r) - float(client_rating_pct)) > 15.0:
                    ok = False
            if (
                client_review_count is not None
                and rev is not None
                and float(client_review_count) > 0
                and float(rev) > 0
            ):
                ratio = float(rev) / float(client_review_count)
                if ratio < 0.12 or ratio > 8.0:
                    ok = False
            if ok:
                similar_ids.add(sid)
        if not similar_ids:
            similar_ids = set(follower_ids)
            cohort_note = "no similar-profile match — fell back to full follower set"

    wins = [win_map[s] for s in similar_ids if s in win_map]
    avg = sum(wins) / len(wins) if wins else None
    return {
        "status": "complete",
        "similar_seller_count": len(similar_ids),
        "follower_seller_count": len(follower_ids),
        "avg_buy_box_win_pct_among_similar": round(avg, 4) if avg is not None else None,
        "cohort_note": cohort_note,
        "note": "Win % is time-on-buy-box in Keepa window, not unit sales share.",
    }


def build_procurement_suggestion(
    plan_mid: float | None,
    plan_low: float | None,
    plan_high: float | None,
    *,
    target_days_cover: float = 30.0,
) -> dict[str, Any]:
    if plan_mid is None or plan_mid <= 0:
        return {"status": "partial", "note": "no positive seller planning monthly velocity"}
    cover = max(1.0, float(target_days_cover))
    units_cover = round(plan_mid * (cover / 30.0))
    daily = round(plan_mid / 30.0, 4)
    lo = round(plan_low) if plan_low is not None and plan_low > 0 else None
    hi = round(plan_high) if plan_high is not None and plan_high > 0 else None
    band = f"{lo}–{hi}" if lo is not None and hi is not None else "n/a"
    return {
        "status": "complete",
        "basis": "seller_planning_monthly_mid",
        "target_days_cover": cover,
        "suggested_monthly_procurement_mid_units": round(plan_mid),
        "suggested_units_for_target_cover": units_cover,
        "implied_daily_velocity_units": daily,
        "planning_band_units_monthly": {"low": lo, "high": hi},
        "prompt_for_buyer": (
            f"Planning velocity ~{round(plan_mid)} units/mo (~{daily}/day); "
            f"for ~{int(cover)}d cover, target ~{units_cover} units on hand (monthly band {band})."
        ),
    }


def build_keepa_possible_upgrades(
    p: dict[str, Any],
    *,
    marketplace_seller_id: str | None,
    buybox_rotation: dict[str, Any],
    offers_list: list[Any] | None,
    listing_economics_reference: dict[str, Any],
    seller_listing_rating_12m_pct: float | None = None,
    seller_listing_review_count: float | None = None,
) -> list[dict[str, Any]]:
    upgrades: list[dict[str, Any]] = []
    if not (marketplace_seller_id or "").strip():
        upgrades.append(
            {
                "code": "provide_marketplace_seller_id",
                "impact": "Align planning to this seller's buy-box share or offer-row share.",
            }
        )
    try:
        r_ok = seller_listing_rating_12m_pct is not None and float(seller_listing_rating_12m_pct) >= 0
    except (TypeError, ValueError):
        r_ok = False
    try:
        v_ok = seller_listing_review_count is not None and float(seller_listing_review_count) >= 0
    except (TypeError, ValueError):
        v_ok = False
    if not (r_ok and v_ok):
        upgrades.append(
            {
                "code": "provide_seller_trust_signals",
                "impact": "Your review count + rating (or stars) enable peer-distance buy-box win-% matching.",
            }
        )
    n = len(offers_list) if isinstance(offers_list, list) else 0
    if n < 20:
        upgrades.append(
            {
                "code": "raise_keepa_product_offers",
                "impact": "Richer offers[], buy-box history, and cohort rating/review signals.",
            }
        )
    le = listing_economics_reference if isinstance(listing_economics_reference, dict) else {}
    if le.get("status") != "complete":
        upgrades.append(
            {
                "code": "enable_keepa_product_stats",
                "impact": "listing_economics_reference_usd (buy box / list) from stats.current.",
            }
        )
    rot = buybox_rotation if isinstance(buybox_rotation, dict) else {}
    if rot.get("status") != "complete":
        upgrades.append(
            {
                "code": "ensure_buybox_history",
                "impact": "Time-on-buy-box win % for entrant vs known seller planning.",
            }
        )
    return upgrades


def augment_keepa_demand_core(
    core: dict[str, Any],
    p: dict[str, Any],
    *,
    method: str | None,
    offers_list: list[Any] | None,
    marketplace_seller_id: str | None,
    seller_listing_rating_12m_pct: float | None,
    seller_listing_review_count: float | None,
    plan_mid: float | None,
    plan_low: float | None,
    plan_high: float | None,
) -> None:
    rot = core.get("buy_box_rotation") or {}
    land = core.get("seller_landscape") or {}
    le = core.get("listing_economics_reference") or {}
    bb_ctx = core.get("buybox_context") if isinstance(core.get("buybox_context"), dict) else {}
    bsl = core.get("buybox_stats_light") if isinstance(core.get("buybox_stats_light"), dict) else {}
    core["buy_box_market_summary"] = build_buy_box_market_summary(
        method=method,
        buybox_rotation=rot,
        seller_landscape=land,
        buybox_context=bb_ctx,
        buybox_stats_light=bsl,
    )
    core["similar_seller_buybox_metrics"] = build_similar_seller_buybox_metrics(
        offers_list,
        rot,
        client_rating_pct=seller_listing_rating_12m_pct,
        client_review_count=seller_listing_review_count,
    )
    core["client_vs_buybox_cohort"] = build_client_vs_buybox_cohort(
        offers_list,
        rot,
        bb_ctx,
        client_rating_pct=seller_listing_rating_12m_pct,
        client_review_count=seller_listing_review_count,
    )
    core["procurement_suggestion"] = build_procurement_suggestion(
        plan_mid, plan_low, plan_high, target_days_cover=30.0
    )
    core["possible_upgrades"] = build_keepa_possible_upgrades(
        p,
        marketplace_seller_id=marketplace_seller_id,
        buybox_rotation=rot,
        offers_list=offers_list,
        listing_economics_reference=le,
        seller_listing_rating_12m_pct=seller_listing_rating_12m_pct,
        seller_listing_review_count=seller_listing_review_count,
    )
    core["inventory_suggestion_guardrails"] = build_inventory_suggestion_guardrails(
        p,
        buybox_stats_light=bsl,
        buy_box_rotation=rot,
    )


def _volume_intelligence_slim_for_api(demand: dict[str, Any]) -> dict[str, Any] | None:
    vi = demand.get("volume_intelligence") if isinstance(demand.get("volume_intelligence"), dict) else None
    if not vi:
        return None
    sig = vi.get("signals") if isinstance(vi.get("signals"), dict) else {}
    return {
        "status": vi.get("status"),
        "model_version": vi.get("model_version"),
        "regime": vi.get("regime"),
        "combined_multiplier": vi.get("combined_multiplier"),
        "relational_multiplier": vi.get("relational_multiplier"),
        "learned_category_scale": vi.get("learned_category_scale"),
        "calibration_samples_for_category": vi.get("calibration_samples_for_category"),
        "review_implied_monthly_units_prior": vi.get("review_implied_monthly_units_prior"),
        "asin_monthly_mid_before_volume_model": vi.get("asin_monthly_mid_before_volume_model"),
        "asin_monthly_mid_after_volume_model": vi.get("asin_monthly_mid_after_volume_model"),
        "listing_gap_reason": vi.get("listing_gap_reason"),
        "regime_note": (str(vi.get("regime_note") or "")[:400] or None),
        "category_key": sig.get("category_key"),
    }


def _opportunity_summary_for_ui(demand: dict[str, Any]) -> dict[str, Any] | None:
    spv = demand.get("seller_planning_velocity") if isinstance(demand.get("seller_planning_velocity"), dict) else {}
    bbwa = demand.get("buybox_window_analysis") if isinstance(demand.get("buybox_window_analysis"), dict) else {}
    by30 = (bbwa.get("by_window_days") or {}).get("30") if isinstance(bbwa.get("by_window_days"), dict) else {}
    market = (
        demand.get("keepa_marketplace_monthly_reference")
        if isinstance(demand.get("keepa_marketplace_monthly_reference"), dict)
        else {}
    )
    pm = demand.get("monthly_units_est_mid")
    mm = market.get("monthly_units_est_mid")
    try:
        pmf = float(pm) if pm is not None else None
    except (TypeError, ValueError):
        pmf = None
    try:
        mmf = float(mm) if mm is not None else None
    except (TypeError, ValueError):
        mmf = None
    opp = None
    if pmf is not None and mmf is not None and mmf > 0:
        opp = round(100.0 * pmf / mmf, 4)
    amazon_30 = by30.get("amazon_share_pct") if isinstance(by30, dict) else None
    amazon_selling = bool(isinstance(amazon_30, (int, float)) and float(amazon_30) > 0)
    sellers_30 = by30.get("distinct_real_sellers") if isinstance(by30, dict) else None
    planning_mode = spv.get("planning_mode")
    rec_yes = not (
        (isinstance(amazon_30, (int, float)) and float(amazon_30) >= 95.0 and (opp is None or opp <= 0.0))
        or planning_mode == "amazon_buybox_30d_only_guardrail"
    )
    return {
        "amazon_selling": amazon_selling,
        "amazon_share_30d_pct": round(float(amazon_30), 4) if isinstance(amazon_30, (int, float)) else None,
        "distinct_buybox_sellers_30d": int(sellers_30) if isinstance(sellers_30, (int, float)) else None,
        "opportunity_pct": opp,
        "est_monthly_units": round(pmf, 2) if pmf is not None else None,
        "market_monthly_units_reference": round(mmf, 2) if mmf is not None else None,
        "planning_mode": planning_mode,
        "recommended_to_sell": bool(rec_yes),
        "recommended_to_sell_label": "Yes" if rec_yes else "No",
    }


def _slim_volume_momentum_for_ui(demand: dict[str, Any]) -> dict[str, Any] | None:
    vi = demand.get("volume_intelligence") if isinstance(demand.get("volume_intelligence"), dict) else None
    if not vi:
        return None
    sig = vi.get("signals") if isinstance(vi.get("signals"), dict) else {}
    delta = sig.get("sales_rank_delta_numeric")
    improved = sig.get("sales_rank_improved_30d")
    nrev = sig.get("new_reviews_30d")
    rank_cur = sig.get("sales_rank_current")
    out: dict[str, Any] = {
        "new_reviews_last_30d": nrev if isinstance(nrev, int) else None,
        "sales_rank_current": rank_cur if isinstance(rank_cur, int) else None,
        "sales_rank_delta_30d": delta if isinstance(delta, int) else None,
        "sales_rank_improved_30d": improved if isinstance(improved, bool) else None,
        "regime": vi.get("regime"),
        "combined_multiplier": vi.get("combined_multiplier"),
        "review_implied_monthly_units_prior": vi.get("review_implied_monthly_units_prior"),
        "volume_intelligence_status": vi.get("status"),
        "listing_gap_reason": vi.get("listing_gap_reason"),
        "volume_model_version": vi.get("model_version"),
    }
    if isinstance(delta, int):
        out["sales_rank_delta_30d_plain_language"] = (
            f"Sales rank improved by {abs(delta):,} vs 30d ago (lower rank = better)."
            if improved
            else (
                f"Sales rank slipped by {delta:,} vs 30d ago (higher rank = slower)."
                if delta > 0
                else "Sales rank roughly flat vs 30d ago."
            )
        )
    else:
        out["sales_rank_delta_30d_plain_language"] = None
    return out


def slim_keepa_planning_for_seller_ui(
    demand: dict[str, Any],
    *,
    marketplace_seller_id: str | None = None,
    top_buybox_sellers: int = 8,
) -> dict[str, Any]:
    """
    JSON-safe subset of ``extract_demand_from_keepa_payload`` for seller results UI
    (no raw ``offers[]`` or full listing blobs).
    """
    if not isinstance(demand, dict):
        return {"status": "partial", "note": "invalid demand payload"}

    sid = (marketplace_seller_id or "").strip() or None
    rot = demand.get("buy_box_rotation") if isinstance(demand.get("buy_box_rotation"), dict) else {}
    win_map: dict[str, float] = {}
    if isinstance(rot.get("win_pct_by_seller"), dict):
        for k, v in rot["win_pct_by_seller"].items():
            ks = str(k)
            if not _is_real_marketplace_seller(ks):
                continue
            try:
                win_map[ks] = float(v)
            except (TypeError, ValueError):
                continue
    items = sorted(win_map.items(), key=lambda x: (-x[1], x[0]))
    win_pct_top = [{"seller_id": a, "win_pct": round(b, 2)} for a, b in items[: max(1, int(top_buybox_sellers))]]

    client_win_pct: float | None = None
    if sid and sid in win_map:
        client_win_pct = round(win_map[sid], 2)

    km = (
        demand.get("keepa_marketplace_monthly_reference")
        if isinstance(demand.get("keepa_marketplace_monthly_reference"), dict)
        else {}
    )
    market_mid = km.get("monthly_units_est_mid")
    try:
        market_mid_n = float(market_mid) if market_mid is not None else None
    except (TypeError, ValueError):
        market_mid_n = None

    plan_mid = demand.get("monthly_units_est_mid")
    plan_low = demand.get("monthly_units_est_low")
    plan_high = demand.get("monthly_units_est_high")
    try:
        pm = float(plan_mid) if plan_mid is not None else None
    except (TypeError, ValueError):
        pm = None
    try:
        plf = float(plan_low) if plan_low is not None else None
    except (TypeError, ValueError):
        plf = None
    try:
        phf = float(plan_high) if plan_high is not None else None
    except (TypeError, ValueError):
        phf = None

    bbm = (
        demand.get("buy_box_market_summary")
        if isinstance(demand.get("buy_box_market_summary"), dict)
        else {}
    )
    proc = (
        demand.get("procurement_suggestion")
        if isinstance(demand.get("procurement_suggestion"), dict)
        else {}
    )
    spv = demand.get("seller_planning_velocity") if isinstance(demand.get("seller_planning_velocity"), dict) else {}
    reasons = spv.get("reasoning")
    reason_short: list[str] = []
    if isinstance(reasons, list):
        for r in reasons[:4]:
            if isinstance(r, str) and r.strip():
                reason_short.append(r.strip()[:220])
            elif r is not None:
                reason_short.append(str(r)[:220])

    upgrades_raw = demand.get("possible_upgrades")
    upgrades_out: list[dict[str, Any]] = []
    if isinstance(upgrades_raw, list):
        for u in upgrades_raw[:12]:
            if isinstance(u, dict) and u.get("code"):
                upgrades_out.append(
                    {
                        "code": str(u.get("code")),
                        "impact": (str(u.get("impact"))[:300] if u.get("impact") else ""),
                    }
                )

    cohort = demand.get("client_vs_buybox_cohort")
    cohort_slim: dict[str, Any] | None = None
    if isinstance(cohort, dict) and cohort.get("status"):
        cohort_slim = {
            "status": cohort.get("status"),
            "note": (str(cohort.get("note"))[:400] if cohort.get("note") else None),
        }
    opp = _opportunity_summary_for_ui(demand)

    return {
        "status": str(demand.get("status") or "partial"),
        "recommended_to_sell": (bool(opp.get("recommended_to_sell")) if opp else None),
        "recommended_to_sell_label": (opp.get("recommended_to_sell_label") if opp else None),
        "planning_method": demand.get("planning_method"),
        "monthly_units_est_mid": pm,
        "monthly_units_est_low": plf,
        "monthly_units_est_high": phf,
        "keepa_market_monthly_units_mid": market_mid_n,
        "buy_box_rotation_status": rot.get("status"),
        "buy_box_rotation_note": (str(rot.get("note") or "")[:400] or None),
        "dominant_seller_id": rot.get("dominant_seller_id"),
        "dominant_win_pct": rot.get("dominant_win_pct"),
        "win_pct_top_sellers": win_pct_top,
        "client_seller_id": sid,
        "client_buy_box_win_pct": client_win_pct,
        "buy_box_market_summary": {
            k: bbm[k]
            for k in (
                "monthly_sales_basis",
                "rotation_status",
                "seller_landscape_status",
                "distinct_buy_box_sellers_in_window",
                "dominant_seller_id",
                "dominant_win_pct",
                "follower_avg_win_pct",
                "offer_row_count",
                "offer_rows_counted",
                "offer_snapshot_unique_sellers",
                "unique_merchants_all_conditions",
                "unique_merchants_new_only",
                "amazon_merchants_in_snapshot",
                "amazon_retail_offer_rows",
                "metric_definitions",
                "note",
            )
            if k in bbm
        },
        "procurement_suggestion": {
            k: proc[k]
            for k in (
                "status",
                "target_days_cover",
                "suggested_monthly_procurement_mid_units",
                "suggested_units_for_target_cover",
                "implied_daily_velocity_units",
                "prompt_for_buyer",
                "planning_band_units_monthly",
            )
            if k in proc
        },
        "seller_planning_velocity": {
            "planning_mode": spv.get("planning_mode"),
            "reasons_short": reason_short,
        },
        "possible_upgrades": upgrades_out,
        "client_vs_buybox_cohort": cohort_slim,
        "momentum_30d_ux": _slim_volume_momentum_for_ui(demand),
        "volume_intelligence_slim": _volume_intelligence_slim_for_api(demand),
        "opportunity_summary_ux": opp,
        "buybox_window_analysis": (
            demand.get("buybox_window_analysis")
            if isinstance(demand.get("buybox_window_analysis"), dict)
            else None
        ),
    }


def extract_demand_from_keepa_payload(
    data: dict[str, Any],
    *,
    marketplace_seller_id: str | None = None,
    seller_listing_rating_12m_pct: float | None = None,
    seller_listing_review_count: float | None = None,
    seller_listing_is_fba: bool | None = None,
) -> dict[str, Any]:
    """
    Accepts full Keepa API JSON (expects `products` list) or a single product dict.
    Returns a normalized dict for SkuDemandSnapshot.derived_json merge.

    **Important:** Keepa ``monthlySold`` is **ASIN / listing** velocity. ``monthly_units_est_*`` are
    **seller planning** estimates. With ``buyBoxSellerIdHistory`` + ``offers``, matched
    ``marketplace_seller_id`` uses that seller's time-on-box share; otherwise **peer-distance** on
    review count + rating (when provided) picks follower win-% to average; else follower average × optional
    similarity multiplier. ASIN-level ``keepa_marketplace_monthly_reference`` is further adjusted by
    ``volume_intelligence`` (rank↔review + optional JSON calibration) when enabled in settings.
    Incomplete extracts (no monthlySold/rank) still return ``volume_intelligence`` / ``momentum_30d_ux`` when csv allows.
    """
    products = data.get("products")
    if products is None and isinstance(data.get("asin"), str):
        products = [data]
    if not products:
        return {
            "status": "skipped",
            "message": "no products in Keepa payload",
        }
    p = products[0] if isinstance(products, list) else products
    if not isinstance(p, dict):
        return {"status": "skipped", "message": "invalid product shape"}

    asin = (p.get("asin") or "").strip() or None
    listing_profile = extract_listing_profile(p)
    cat_primary = listing_profile.get("category_primary_for_heuristics")
    cat_factor = category_velocity_factor(cat_primary)

    monthly_sold = _safe_int(p.get("monthlySold"))
    if monthly_sold is None:
        ms = p.get("monthlySold")
        if isinstance(ms, (int, float)) and ms == -1:
            monthly_sold = None

    rank = _sales_rank_from_product(p)

    from unie_cortex.config import settings as _kset

    offers_list = p.get("offers") if isinstance(p.get("offers"), list) else None
    offers_digest = normalize_offers_by_seller(
        offers_list,
        assume_unknown_condition_is_new=bool(
            getattr(_kset, "keepa_assume_unknown_condition_is_new", True)
        ),
        max_sellers=int(getattr(_kset, "keepa_offers_digest_max_sellers", 250) or 250),
        lu_minute=_safe_int(p.get("lastUpdate")),
    )
    bb = extract_buybox_signals(p, offers_digest=offers_digest)
    seller_landscape = extract_seller_landscape_from_offers(
        p, bb.get("buy_box_seller_id"), offers_digest=offers_digest
    )
    buybox_stats_light = extract_buybox_stats_light(p)
    buy_box_rotation = extract_buybox_rotation_profile(p, window_days=30.0)
    buybox_window_analysis = build_buybox_window_analysis(p, decision_window_days=30.0)
    listing_economics_reference = extract_listing_economics_reference_usd(p)

    seller_prof: dict[str, Any] = {}
    if seller_listing_rating_12m_pct is not None:
        seller_prof["listing_rating_12m_pct"] = seller_listing_rating_12m_pct
    if seller_listing_review_count is not None:
        seller_prof["listing_review_count"] = seller_listing_review_count
    if seller_listing_is_fba is not None:
        seller_prof["listing_is_fba"] = seller_listing_is_fba

    from unie_cortex.services.placement_signals import build_placement_hints
    from unie_cortex.services.placement_summary import build_inventory_placement_summary

    if monthly_sold and monthly_sold > 0:
        low = round(monthly_sold * 0.75, 2)
        high = round(monthly_sold * 1.33, 2)
        mid = float(monthly_sold)
        method = "keepa_monthlySold"
        mid, low, high, adj_meta = _apply_category_monthly(mid, low, high, cat_factor)
    elif rank:
        low, high = _rank_to_monthly_units_band(rank)
        mid = round(math.sqrt(max(low * high, 1.0)), 2)
        method = "keepa_salesRank_heuristic"
        mid, low, high, adj_meta = _apply_category_rank(mid, low, high, cat_factor)
    else:
        from unie_cortex.config import settings as _vol_settings_inc
        from unie_cortex.integrations.keepa_volume_model import build_volume_intelligence_without_monthly_baseline

        bb_only = bb
        inv = build_inventory_placement_summary(
            asin=asin,
            title=listing_profile.get("title"),
            product_origin_postal=None,
            monthly_units_est_mid=None,
            suggested_min_active_warehouses=1,
            warehouse_nodes=[],
        )
        _vm_ver = str(
            getattr(_vol_settings_inc, "keepa_volume_model_version", "cortex_volume_v1") or "cortex_volume_v1"
        )
        _vi_partial = None
        _mom_partial = None
        if getattr(_vol_settings_inc, "keepa_volume_intelligence_enabled", True):
            _vi_partial = build_volume_intelligence_without_monthly_baseline(
                p,
                cat_primary,
                gap_reason="no monthlySold or usable sales rank in Keepa snapshot",
                model_version=_vm_ver,
                calibration_path=getattr(_vol_settings_inc, "volume_calibration_store_path", None),
            )
            _mom_partial = _slim_volume_momentum_for_ui({"volume_intelligence": _vi_partial})
        _opp_partial = _opportunity_summary_for_ui(
            {
                "monthly_units_est_mid": None,
                "keepa_marketplace_monthly_reference": {},
                "seller_planning_velocity": {},
                "buybox_window_analysis": buybox_window_analysis,
            }
        )
        inc = {
            "status": "incomplete",
            "message": "no monthlySold or usable sales rank",
            "asin": asin,
            "recommended_to_sell": (bool(_opp_partial.get("recommended_to_sell")) if _opp_partial else None),
            "recommended_to_sell_label": (_opp_partial.get("recommended_to_sell_label") if _opp_partial else None),
            "listing_profile": listing_profile,
            "listing_economics_reference": listing_economics_reference,
            "buybox_context": bb_only,
            "buybox_stats_light": buybox_stats_light,
            "buy_box_rotation": buy_box_rotation,
            "buybox_window_analysis": buybox_window_analysis,
            "seller_landscape": seller_landscape,
            "category_heuristic": {"primary_label": cat_primary, "velocity_factor_if_applied": cat_factor},
            "inventory_placement_summary": inv,
            "volume_intelligence": _vi_partial,
            "momentum_30d_ux": _mom_partial,
            "volume_intelligence_slim": (
                _volume_intelligence_slim_for_api({"volume_intelligence": _vi_partial}) if _vi_partial else None
            ),
            "opportunity_summary_ux": _opp_partial,
            "keepa_offers_digest": offers_digest,
            "keepa_trend_bundle": build_keepa_trend_bundle(
                p, plan_mid=None, plan_low=None, plan_high=None, target_days_cover=30.0
            ),
        }
        augment_keepa_demand_core(
            inc,
            p,
            method=None,
            offers_list=offers_list,
            marketplace_seller_id=marketplace_seller_id,
            seller_listing_rating_12m_pct=seller_listing_rating_12m_pct,
            seller_listing_review_count=seller_listing_review_count,
            plan_mid=None,
            plan_low=None,
            plan_high=None,
        )
        return inc

    from unie_cortex.config import settings as _vol_settings
    from unie_cortex.integrations.keepa_volume_model import apply_keepa_volume_intelligence

    volume_intelligence: dict[str, Any] | None = None
    _pre_vol_mid = float(mid)
    _pre_vol_low = float(low)
    _pre_vol_high = float(high)
    if getattr(_vol_settings, "keepa_volume_intelligence_enabled", True) and mid and float(mid) > 0:
        _vi = apply_keepa_volume_intelligence(
            p,
            float(mid),
            float(low),
            float(high),
            cat_primary,
            calibration_path=getattr(_vol_settings, "volume_calibration_store_path", None),
            model_version=str(getattr(_vol_settings, "keepa_volume_model_version", "cortex_volume_v1") or "cortex_volume_v1"),
        )
        mid, low, high = float(_vi["mid"]), float(_vi["low"]), float(_vi["high"])
        volume_intelligence = _vi["meta"]
        volume_intelligence["asin_monthly_mid_before_volume_model"] = round(_pre_vol_mid, 2)
        volume_intelligence["asin_monthly_mid_after_volume_model"] = round(float(mid), 2)
        volume_intelligence["asin_monthly_low_high_before_volume_model"] = {
            "low": round(_pre_vol_low, 2),
            "high": round(_pre_vol_high, 2),
        }

    plan_mid, plan_low, plan_high, planning_meta = apply_seller_scoped_monthly_planning(
        mid,
        low,
        high,
        product=p,
        competition_level=str(bb.get("competition_level") or "unknown"),
        buy_box_seller_id=bb.get("buy_box_seller_id"),
        marketplace_seller_id=marketplace_seller_id,
        seller_landscape=seller_landscape,
        buybox_rotation=buy_box_rotation,
        offers=offers_list,
        seller_listing_profile=seller_prof or None,
    )

    hints = build_placement_hints(monthly_units_est_mid=plan_mid, buybox_context=bb)
    inv = build_inventory_placement_summary(
        asin=asin,
        title=listing_profile.get("title"),
        product_origin_postal=None,
        monthly_units_est_mid=plan_mid,
        suggested_min_active_warehouses=int(hints.get("suggested_min_active_warehouses") or 1),
        warehouse_nodes=[],
    )

    core: dict[str, Any] = {
        "status": "complete",
        "asin": asin,
        "monthly_units_est_mid": plan_mid,
        "monthly_units_est_low": plan_low,
        "monthly_units_est_high": plan_high,
        "keepa_marketplace_monthly_reference": {
            "monthly_units_est_mid": mid,
            "monthly_units_est_low": low,
            "monthly_units_est_high": high,
            "note": "ASIN-level band after category tweak + volume_intelligence (rank↔review + optional calibration) — not your SKU sales without seller match.",
        },
        "seller_planning_velocity": planning_meta,
        "buy_box_rotation": buy_box_rotation,
        "buybox_window_analysis": buybox_window_analysis,
        "sales_rank_used": rank,
        "method": method,
        "planning_method": str(planning_meta.get("planning_mode") or "seller_planning"),
        "note": (
            "monthly_units_est_* = seller planning band. keepa_marketplace_monthly_reference = ASIN velocity. "
            "With buyBoxSellerIdHistory: seller id match, peer cohort (reviews+rating), or follower average. "
            "Blend with WMS / label history when available."
        ),
        "listing_profile": listing_profile,
        "listing_economics_reference": listing_economics_reference,
        "buybox_context": bb,
        "buybox_stats_light": buybox_stats_light,
        "seller_landscape": seller_landscape,
        "category_heuristic": {
            "primary_label": cat_primary,
            "velocity_factor_applied": adj_meta.get("category_velocity_factor"),
            "adjustment_detail": adj_meta,
        },
        "volume_intelligence": volume_intelligence,
        "momentum_30d_ux": (
            _slim_volume_momentum_for_ui({"volume_intelligence": volume_intelligence})
            if volume_intelligence
            else None
        ),
        "volume_intelligence_slim": (
            _volume_intelligence_slim_for_api({"volume_intelligence": volume_intelligence})
            if volume_intelligence
            else None
        ),
        "opportunity_summary_ux": _opportunity_summary_for_ui(
            {
                "monthly_units_est_mid": plan_mid,
                "keepa_marketplace_monthly_reference": {
                    "monthly_units_est_mid": mid,
                },
                "seller_planning_velocity": planning_meta,
                "buybox_window_analysis": buybox_window_analysis,
            }
        ),
        "placement_hints": hints,
        "inventory_placement_summary": inv,
        "monthly_sales_history_6m": extract_keepa_monthly_sales_history_6m(
            p, seller_monthly_units_mid=float(plan_mid) if plan_mid is not None else None
        ),
        "keepa_offers_digest": offers_digest,
        "keepa_trend_bundle": build_keepa_trend_bundle(
            p,
            plan_mid=float(plan_mid) if plan_mid is not None else None,
            plan_low=float(plan_low) if plan_low is not None else None,
            plan_high=float(plan_high) if plan_high is not None else None,
            target_days_cover=30.0,
        ),
    }
    _opp_core = core.get("opportunity_summary_ux") if isinstance(core.get("opportunity_summary_ux"), dict) else None
    core["recommended_to_sell"] = bool(_opp_core.get("recommended_to_sell")) if _opp_core else None
    core["recommended_to_sell_label"] = _opp_core.get("recommended_to_sell_label") if _opp_core else None
    augment_keepa_demand_core(
        core,
        p,
        method=method,
        offers_list=offers_list,
        marketplace_seller_id=marketplace_seller_id,
        seller_listing_rating_12m_pct=seller_listing_rating_12m_pct,
        seller_listing_review_count=seller_listing_review_count,
        plan_mid=plan_mid,
        plan_low=plan_low,
        plan_high=plan_high,
    )
    return core

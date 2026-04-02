"""Blend per-SKU shipping observations with a donor SKU in the same physical bucket."""

from __future__ import annotations

from typing import Any

from unie_cortex.config import settings


def _line_money(row: dict[str, Any]) -> float | None:
    if row.get("line_amount_usd") is not None:
        return float(row["line_amount_usd"])
    if row.get("label_amount_usd") is not None:
        return float(row["label_amount_usd"])
    return None


def compute_own_shipping_stats(sku: str, label_rows: list[dict[str, Any]]) -> dict[str, Any]:
    lines = [r for r in label_rows if (r.get("sku") or "").strip() == sku]
    amounts = [m for r in lines if (m := _line_money(r)) is not None]
    weights = [float(r["weight_lb"]) for r in lines if r.get("weight_lb") is not None]
    carriers: dict[str, int] = {}
    for r in lines:
        c = r.get("carrier") or "unknown"
        carriers[c] = carriers.get(c, 0) + 1
    return {
        "sku": sku,
        "label_line_count": len(lines),
        "avg_label_amount_usd": round(sum(amounts) / len(amounts), 4) if amounts else None,
        "avg_weight_lb": round(sum(weights) / len(weights), 4) if weights else None,
        "carrier_mix": carriers,
    }


def pick_donor(
    sku: str,
    signature: str,
    sku_to_stats: dict[str, dict[str, Any]],
    signature_to_skus: dict[str, list[str]],
) -> str | None:
    peers = [s for s in signature_to_skus.get(signature, []) if s != sku]
    if not peers:
        return None
    best = None
    best_n = -1
    for p in peers:
        n = (sku_to_stats.get(p) or {}).get("label_line_count") or 0
        if n > best_n:
            best_n = n
            best = p
    return best if best_n > 0 else None


def merge_shipping_intelligence(
    sku: str,
    own: dict[str, Any],
    donor: dict[str, Any] | None,
    *,
    min_obs: int | None = None,
) -> dict[str, Any]:
    """
    If own label_line_count < min_obs and donor has data, blend averages and mark provenance.
    Weight on own grows linearly with own count / min_obs.
    """
    thr = min_obs if min_obs is not None else settings.sku_inherit_min_label_lines
    n_own = int(own.get("label_line_count") or 0)
    if donor is None or n_own >= thr:
        return {
            "sku": sku,
            "effective": own,
            "provenance": {"source": "own_only", "confidence": 1.0},
        }

    n_d = int(donor.get("label_line_count") or 0)
    if n_d <= 0:
        return {
            "sku": sku,
            "effective": own,
            "provenance": {"source": "own_only", "donor_unavailable": True},
        }

    w_own = min(1.0, n_own / thr) if thr else 1.0
    w_donor = 1.0 - w_own

    def blend(a: float | None, b: float | None) -> float | None:
        if a is None and b is None:
            return None
        if a is None:
            return round(float(b) * w_donor, 4) if w_donor else None
        if b is None:
            return round(float(a) * w_own, 4) if w_own else None
        return round(float(a) * w_own + float(b) * w_donor, 4)

    effective = {
        "sku": sku,
        "label_line_count": n_own,
        "avg_label_amount_usd": blend(
            own.get("avg_label_amount_usd"),
            donor.get("avg_label_amount_usd"),
        ),
        "avg_weight_lb": blend(own.get("avg_weight_lb"), donor.get("avg_weight_lb")),
        "carrier_mix": dict(own.get("carrier_mix") or {}),
        "donor_carrier_mix": dict(donor.get("carrier_mix") or {}),
    }

    return {
        "sku": sku,
        "effective": effective,
        "provenance": {
            "source": "blended_physical_twin",
            "inherited_from_sku": donor.get("sku"),
            "weight_on_own": round(w_own, 4),
            "weight_on_donor": round(w_donor, 4),
            "until": f"{thr} label lines for this SKU",
            "confidence": round(0.35 + 0.65 * w_own, 4),
        },
    }

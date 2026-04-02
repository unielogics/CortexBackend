"""
Default U.S. e-commerce demand share by state (planning prior).

Normalized to 48 contiguous hubs (AK/HI excluded; DC folded into MD).
"""

from __future__ import annotations

from typing import Any

from unie_cortex.services.warehouse_mock_rate_grid import CONTIGUOUS_STATE_HUB_DESTINATIONS_48

_RAW_PCT: dict[str, float] = {
    "CA": 11.8, "TX": 8.9, "FL": 7.1, "NY": 6.4, "IL": 4.1, "PA": 3.9, "OH": 3.6, "GA": 3.4,
    "NC": 3.2, "MI": 3.1, "NJ": 2.8, "VA": 2.6, "WA": 2.4, "AZ": 2.2, "MA": 2.1, "TN": 2.0,
    "IN": 1.9, "MD": 1.8, "MO": 1.7, "WI": 1.6, "CO": 1.6, "MN": 1.5, "SC": 1.5, "AL": 1.4,
    "LA": 1.3, "KY": 1.2, "OR": 1.1, "OK": 1.1, "CT": 1.0, "UT": 0.9, "IA": 0.8, "NV": 0.8,
    "AR": 0.8, "MS": 0.7, "KS": 0.7, "NM": 0.5, "NE": 0.5, "ID": 0.5, "WV": 0.4, "NH": 0.4,
    "ME": 0.3, "MT": 0.3, "RI": 0.3, "DE": 0.3, "SD": 0.2, "ND": 0.2, "DC": 0.2, "VT": 0.1,
    "WY": 0.1, "AK": 0.2, "HI": 0.4,
}

_CONTIGUOUS_STATES: frozenset[str] = frozenset(m["state"] for m in CONTIGUOUS_STATE_HUB_DESTINATIONS_48)


def contiguous_state_demand_shares_normalized() -> dict[str, float]:
    merged = dict(_RAW_PCT)
    dc = float(merged.pop("DC", 0.0))
    merged["MD"] = float(merged.get("MD", 0.0)) + dc
    raw_contiguous = {st: float(merged[st]) for st in _CONTIGUOUS_STATES if st in merged}
    total = sum(raw_contiguous.values())
    if total <= 0:
        u = 1.0 / len(_CONTIGUOUS_STATES)
        return {m["state"]: u for m in CONTIGUOUS_STATE_HUB_DESTINATIONS_48}
    return {st: v / total for st, v in raw_contiguous.items()}


def label_rollup_hot_state_attachment(rollup: dict[str, Any]) -> dict[str, Any]:
    """
    ZIP3 hot/medium/cold tiers and top destination states from label lines.
    Merged into placement_mock_rate_grids.demand_weighting for UI + Intelligence Network dock.
    """
    if rollup.get("status") != "complete":
        return {}
    tiers = rollup.get("tiers") if isinstance(rollup.get("tiers"), dict) else {}
    bs = rollup.get("by_state") if isinstance(rollup.get("by_state"), dict) else {}
    sorted_st = sorted(
        bs.items(),
        key=lambda kv: float((kv[1] or {}).get("lines") or 0),
        reverse=True,
    )[:15]
    top_states = [
        {
            "state": st,
            "lines": int((v or {}).get("lines") or 0),
            "pct_of_lines": (v or {}).get("pct_of_lines"),
        }
        for st, v in sorted_st
    ]
    return {
        "label_zip3_demand_tiers": {
            "hot_zip3": list(tiers.get("hot_zip3") or []),
            "medium_zip3": list(tiers.get("medium_zip3") or []),
            "cold_zip3": list(tiers.get("cold_zip3") or []),
        },
        "label_by_state_top_lines": top_states,
        "label_distinct_zip3_count": rollup.get("zip3_count"),
    }


def demand_share_metadata() -> dict[str, Any]:
    from unie_cortex.config import settings

    return {
        "assumptions_version": "us_state_demand_share_v1",
        "contiguous_states_count": len(_CONTIGUOUS_STATES),
        "excluded_from_denominator": ["AK", "HI"],
        "dc_folded_into": "MD",
        "forecast_id": getattr(settings, "us_state_demand_forecast_id", ""),
        "effective_as_of": getattr(settings, "us_state_demand_forecast_effective_as_of", ""),
        "refresh_policy": getattr(settings, "us_state_demand_forecast_refresh_note", ""),
        "seasonality_note": "Static shares — no within-year seasonal adjustment in-model.",
        "note": "Planning prior; override with label-derived state mix when available.",
    }


def build_blended_state_demand_weights_from_labels(
    labels: list[dict[str, Any]],
    *,
    min_label_lines_for_full_blend: float | None = None,
) -> tuple[dict[str, float], dict[str, Any]]:
    """
    Merge label rollup (dest_postal → state via demand_rollup) with the default 48-state prior.

    ``blend_lambda`` ramps 0→1 with label line volume so sparse history does not overfit.
    """
    from unie_cortex.config import settings
    from unie_cortex.network.demand_rollup import rollup_label_demand

    default = contiguous_state_demand_shares_normalized()
    floor = float(
        min_label_lines_for_full_blend
        if min_label_lines_for_full_blend is not None
        else getattr(settings, "label_state_weight_blend_min_lines", 200.0) or 200.0
    )
    floor = max(1.0, floor)

    meta_base = demand_share_metadata()
    rollup = rollup_label_demand(labels)
    hot_att = label_rollup_hot_state_attachment(rollup)
    if rollup.get("status") != "complete":
        return default, {
            **meta_base,
            **hot_att,
            "demand_weight_source": "default_48_state_prior_only",
            "demand_weight_confidence": "mostly_default",
            "label_total_lines": 0,
            "blend_lambda": 0.0,
            "rollup_status": rollup.get("status"),
        }

    by_state = rollup.get("by_state") or {}
    total_lines = float(rollup.get("total_label_lines") or 0)
    lines_by_st: dict[str, float] = {}
    for st, v in by_state.items():
        if st not in _CONTIGUOUS_STATES:
            continue
        if isinstance(v, dict):
            lines_by_st[str(st)] = float(v.get("lines") or 0)

    if total_lines <= 0 or not lines_by_st:
        return default, {
            **meta_base,
            **hot_att,
            "demand_weight_source": "default_48_state_prior_only",
            "demand_weight_confidence": "mostly_default",
            "label_total_lines": int(total_lines),
            "blend_lambda": 0.0,
            "rollup_status": "complete",
        }

    lam = min(1.0, total_lines / floor)
    label_share = {st: lines_by_st[st] / total_lines for st in lines_by_st}

    merged: dict[str, float] = {}
    for st, d_sh in default.items():
        merged[st] = lam * float(label_share.get(st, 0.0)) + (1.0 - lam) * float(d_sh)

    tot = sum(merged.values())
    if tot <= 1e-12:
        return default, {
            **meta_base,
            **hot_att,
            "demand_weight_source": "default_48_state_prior_fallback",
            "demand_weight_confidence": "mostly_default",
            "label_total_lines": int(total_lines),
            "blend_lambda": lam,
        }

    norm = {k: v / tot for k, v in merged.items()}

    if lam < 0.15:
        conf = "mostly_default"
    elif lam > 0.85:
        conf = "label_heavy"
    else:
        conf = "blended"

    preview = sorted(norm.items(), key=lambda kv: -kv[1])[:12]

    return norm, {
        **meta_base,
        **hot_att,
        "demand_weight_source": "blended_label_lines_and_default_prior",
        "demand_weight_confidence": conf,
        "label_total_lines": int(total_lines),
        "blend_lambda": round(lam, 6),
        "min_label_lines_for_full_blend": floor,
        "state_weights_preview": [{"state": st, "share": round(w, 6)} for st, w in preview],
        "rollup_status": "complete",
        "state_rollup_method": rollup.get("state_rollup_method"),
    }

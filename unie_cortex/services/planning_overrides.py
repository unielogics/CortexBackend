"""Run-body overrides for Product Research / item intelligence planning velocity."""

from __future__ import annotations

import math
from typing import Any

from unie_cortex.config import settings
from unie_cortex.integrations.keepa_demand import seller_inputs_from_catalog_row


def merge_planning_seller_inputs(
    row: dict[str, Any],
    sku: str,
    planning_marketplace_seller_id_by_sku: dict[str, str] | None,
) -> dict[str, Any]:
    """
    Catalog seller fields + optional per-SKU marketplace seller id from the request body.

    Body value wins for ``marketplace_seller_id`` so a single run can force Keepa buy-box / offer
    matching without rewriting catalog.
    """
    si = seller_inputs_from_catalog_row(row)
    if not planning_marketplace_seller_id_by_sku:
        return si
    key = str(sku).strip()
    raw = planning_marketplace_seller_id_by_sku.get(key)
    if raw is None:
        return si
    sid = str(raw).strip()
    if not sid:
        return si
    out = {**si, "marketplace_seller_id": sid}
    out["planning_marketplace_seller_id_source"] = "request_body_by_sku"
    return out


def apply_planning_monthly_units_overrides(
    demand_by_sku: dict[str, dict[str, Any]],
    overrides: dict[str, float] | None,
) -> dict[str, Any]:
    """
    Replace ``monthly_units_est_{mid,low,high}`` for listed SKUs before allocation.

    Scales low/high proportionally to mid when both exist; otherwise uses 0.75× / 1.33× bands.
    """
    meta: dict[str, Any] = {"applied": {}, "skipped": []}
    if not overrides:
        return meta
    for sku_key, raw in overrides.items():
        sku = str(sku_key).strip()
        if not sku:
            meta["skipped"].append({"sku": sku_key, "reason": "empty_key"})
            continue
        if sku not in demand_by_sku:
            meta["skipped"].append({"sku": sku, "reason": "not_in_demand_by_sku"})
            continue
        try:
            v = float(raw)
        except (TypeError, ValueError):
            meta["skipped"].append({"sku": sku, "reason": "not_numeric"})
            continue
        if v < 0 or math.isnan(v) or math.isinf(v):
            meta["skipped"].append({"sku": sku, "reason": "out_of_range"})
            continue
        min_manual = int(getattr(settings, "planning_manual_monthly_units_override_minimum", 150) or 0)
        if min_manual > 0 and v < float(min_manual):
            meta["skipped"].append(
                {
                    "sku": sku,
                    "reason": "below_manual_override_minimum",
                    "minimum_units": min_manual,
                    "value": v,
                }
            )
            continue
        dem = demand_by_sku[sku]
        if not isinstance(dem, dict):
            meta["skipped"].append({"sku": sku, "reason": "demand_not_object"})
            continue
        baseline = dem.get("monthly_units_est_mid")
        try:
            bmid = float(baseline) if baseline is not None else None
        except (TypeError, ValueError):
            bmid = None
        low = dem.get("monthly_units_est_low")
        high = dem.get("monthly_units_est_high")
        ratio = 1.0
        if bmid is not None and abs(bmid) > 1e-12:
            ratio = v / bmid

        def _scale(x: Any) -> float | None:
            try:
                xf = float(x)
                return max(0.0, round(xf * ratio, 4))
            except (TypeError, ValueError):
                return None

        nlow = _scale(low) if low is not None else max(0.0, round(v * 0.75, 2))
        nhigh = _scale(high) if high is not None else max(nlow or 0.0, round(v * 1.33, 2))
        if nlow is None:
            nlow = max(0.0, round(v * 0.75, 2))
        if nhigh is None:
            nhigh = max(float(nlow), round(v * 1.33, 2))

        dem["monthly_units_est_mid"] = round(v, 4)
        dem["monthly_units_est_low"] = float(nlow)
        dem["monthly_units_est_high"] = float(nhigh)
        block = {
            "user_monthly_units_mid": round(v, 4),
            "baseline_monthly_units_est_mid": baseline,
            "note": (
                "Request planning_monthly_units_override_by_sku — replaces modeled seller planning mid for "
                "this run (allocation, network trim, LTL, placement summary after origin merge)."
            ),
        }
        dem["planning_monthly_units_override"] = block
        meta["applied"][sku] = block
    return meta


def integerize_monthly_unit_fields_in_demand_by_sku(demand_by_sku: dict[str, dict[str, Any]]) -> None:
    """
    Demand and reference bands are counted in whole sellable units (no fractional SKUs in API output).

    Internal modeling may use floats until this runs — typically immediately after Keepa extract + overrides,
    before allocation inputs are built.
    """
    keys = ("monthly_units_est_mid", "monthly_units_est_low", "monthly_units_est_high")

    def _round_keys(d: dict[str, Any]) -> None:
        for key in keys:
            if key not in d or d[key] is None:
                continue
            try:
                d[key] = max(0, int(round(float(d[key]))))
            except (TypeError, ValueError):
                continue

    for dem in demand_by_sku.values():
        if not isinstance(dem, dict):
            continue
        _round_keys(dem)
        ref = dem.get("keepa_marketplace_monthly_reference")
        if isinstance(ref, dict):
            _round_keys(ref)
        raw_mid = dem.get("keepa_market_monthly_units_mid")
        if raw_mid is not None:
            try:
                dem["keepa_market_monthly_units_mid"] = max(0, int(round(float(raw_mid))))
            except (TypeError, ValueError):
                pass
        pov = dem.get("planning_monthly_units_override")
        if isinstance(pov, dict) and pov.get("user_monthly_units_mid") is not None:
            try:
                pov["user_monthly_units_mid"] = max(0, int(round(float(pov["user_monthly_units_mid"]))))
            except (TypeError, ValueError):
                pass

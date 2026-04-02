"""Fuel cost estimates and driver daily fuel forecast using EIA snapshots."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Literal
from zoneinfo import ZoneInfo

from unie_cortex.config import settings
from unie_cortex.integrations.eia_client import fetch_series_latest
from unie_cortex.integrations.eia_series_registry import (
    DIESEL_US_WEEKLY,
    GASOLINE_REGULAR_US_WEEKLY,
)
from unie_cortex.network.tms_schemas import ProposeRoutesRequest

FuelPref = Literal["diesel", "gasoline"]


def series_for_fuel(fuel: FuelPref) -> str:
    return DIESEL_US_WEEKLY if fuel == "diesel" else GASOLINE_REGULAR_US_WEEKLY


def eia_price_snapshot(fuel: FuelPref) -> dict[str, Any]:
    return fetch_series_latest(series_for_fuel(fuel))


def _km_to_mi(km: float) -> float:
    return km / 1.609344


def resolve_tractor_mpg(req: Any, driver: Any = None) -> dict[str, Any]:
    """
    Precedence: ``driver.tractor_mpg`` > ``req.tractor_mpg`` > ``DEFAULT_TRACTOR_MPG``.
    """
    default = float(settings.default_tractor_mpg or 6.5)
    d_raw = getattr(driver, "tractor_mpg", None) if driver is not None else None
    r_raw = getattr(req, "tractor_mpg", None)
    d_mpg = float(d_raw) if d_raw is not None and float(d_raw) > 0 else None
    r_mpg = float(r_raw) if r_raw is not None and float(r_raw) > 0 else None

    if d_mpg is not None:
        src = "driver"
        resolved = d_mpg
    elif r_mpg is not None:
        src = "request"
        resolved = r_mpg
    else:
        src = "default"
        resolved = default

    return {
        "tractor_mpg": resolved,
        "tractor_mpg_source": src,
        "tractor_mpg_from_driver": d_mpg,
        "tractor_mpg_from_request": r_mpg,
        "default_tractor_mpg": default,
    }


def _mpg_for_request(req: Any, driver: Any = None) -> float:
    return float(resolve_tractor_mpg(req, driver)["tractor_mpg"])


def _fuel_pref(req: ProposeRoutesRequest) -> FuelPref:
    return "gasoline" if req.fuel_type_preference == "gasoline" else "diesel"


def fuel_cost_for_route_usd(
    empty_mi: float,
    loaded_mi: float,
    req: ProposeRoutesRequest,
    *,
    driver: Any = None,
) -> dict[str, Any] | None:
    snap = eia_price_snapshot(_fuel_pref(req))
    if not snap.get("ok"):
        return None
    ppg = float(snap["price_usd_per_gallon"])
    mpg_ctx = resolve_tractor_mpg(req, driver)
    mpg = float(mpg_ctx["tractor_mpg"])
    total_mi = max(0.0, empty_mi + loaded_mi)
    gal = total_mi / mpg if mpg > 0 else 0.0
    return {
        "fuel_cost_usd_est": round(gal * ppg, 2),
        "gallons_est": round(gal, 3),
        "tractor_mpg": mpg,
        "tractor_mpg_source": mpg_ctx["tractor_mpg_source"],
        "tractor_mpg_from_request": mpg_ctx["tractor_mpg_from_request"],
        "tractor_mpg_from_driver": mpg_ctx["tractor_mpg_from_driver"],
        "default_tractor_mpg": mpg_ctx["default_tractor_mpg"],
        "mpg_assumption": mpg,
        "empty_miles": round(empty_mi, 2),
        "loaded_miles": round(loaded_mi, 2),
        "eia": snap,
    }


def miles_on_planning_date_from_legs(
    legs: list[dict[str, Any]],
    *,
    planning_date: date,
    driver_timezone: str,
) -> tuple[float, str]:
    """
    Apportion leg miles to a local calendar day using ETA overlap (wall time in zone).
    """
    try:
        tz = ZoneInfo(driver_timezone.strip() or "UTC")
    except Exception:
        tz = timezone.utc
    day_start = datetime.combine(planning_date, time.min, tzinfo=tz)
    day_end = day_start + timedelta(days=1)
    total = 0.0
    for leg in legs:
        dep_s = leg.get("eta_departure_utc")
        arr_s = leg.get("eta_arrival_utc")
        dk = float(leg.get("distance_km") or 0.0)
        mi = _km_to_mi(dk)
        if not dep_s or not arr_s or mi <= 0:
            continue
        try:
            dep = datetime.fromisoformat(dep_s.replace("Z", "+00:00"))
            arr = datetime.fromisoformat(arr_s.replace("Z", "+00:00"))
        except ValueError:
            continue
        if arr <= dep:
            continue
        dep_l = dep.astimezone(tz)
        arr_l = arr.astimezone(tz)
        leg_start = max(dep_l, day_start)
        leg_end = min(arr_l, day_end)
        if leg_end <= leg_start:
            continue
        overlap = (leg_end - leg_start).total_seconds()
        leg_total = (arr_l - dep_l).total_seconds()
        if leg_total <= 0:
            continue
        frac = min(1.0, max(0.0, overlap / leg_total))
        total += mi * frac
    note = "miles_apportioned_by_eta_overlap_in_driver_timezone"
    return round(total, 2), note


def driver_daily_fuel_forecast(
    legs: list[dict[str, Any]],
    req: Any,
    *,
    driver: Any = None,
) -> dict[str, Any]:
    """Planning benchmark for fuel spend (see plan §5.4)."""
    fuel = _fuel_pref(req)
    mpg_ctx = resolve_tractor_mpg(req, driver)
    mpg = float(mpg_ctx["tractor_mpg"])
    snap = eia_price_snapshot(fuel)
    out: dict[str, Any] = {
        "fuel_type": fuel,
        "tractor_mpg": mpg,
        "tractor_mpg_source": mpg_ctx["tractor_mpg_source"],
        "tractor_mpg_from_request": mpg_ctx["tractor_mpg_from_request"],
        "tractor_mpg_from_driver": mpg_ctx["tractor_mpg_from_driver"],
        "default_tractor_mpg": mpg_ctx["default_tractor_mpg"],
        "mpg_assumption": mpg,
        "eia_price": snap,
    }
    if not snap.get("ok"):
        out["status"] = "skipped"
        out["reason"] = snap.get("reason") or snap.get("error") or "eia_unavailable"
        return out

    ppg = float(snap["price_usd_per_gallon"])
    tz_name = (req.driver_timezone or "").strip() or "UTC"
    if req.miles_override_today is not None:
        miles_day = float(req.miles_override_today)
        mile_note = (
            "miles_from_override_with_planning_date"
            if req.planning_date is not None
            else "miles_from_override_standalone"
        )
    elif req.planning_date is not None:
        miles_day, mile_note = miles_on_planning_date_from_legs(
            legs,
            planning_date=req.planning_date,
            driver_timezone=tz_name,
        )
    else:
        miles_day = round(sum(_km_to_mi(float(l.get("distance_km") or 0.0)) for l in legs), 2)
        mile_note = "full_route_miles_used_as_day_proxy_no_planning_date"

    gal = miles_day / mpg if mpg > 0 else 0.0
    usd = gal * ppg
    stale = None
    if isinstance(snap.get("period"), str) and len(snap["period"]) >= 8:
        try:
            raw = snap["period"]
            if len(raw) >= 8:
                y, m, d = int(raw[:4]), int(raw[4:6]), int(raw[6:8])
                obs = date(y, m, d)
                today = date.today()
                stale = (today - obs).days
        except (ValueError, TypeError):
            stale = None

    out["status"] = "complete"
    out["fuel_expense_usd_est"] = round(usd, 2)
    out["breakdown"] = {
        "miles_day": miles_day,
        "miles_note": mile_note,
        "tractor_mpg": mpg,
        "tractor_mpg_source": mpg_ctx["tractor_mpg_source"],
        "mpg": mpg,
        "gallons_est": round(gal, 3),
        "price_usd_per_gallon": ppg,
        "eia_series_id": snap.get("series_id"),
        "eia_period": snap.get("period"),
        "driver_timezone": tz_name,
        "planning_date": req.planning_date.isoformat() if req.planning_date else None,
    }
    if stale is not None:
        out["price_staleness_days"] = stale
    out["note"] = (
        "Planning benchmark: EIA macro price × miles × MPG — not an actual pump quote for the day."
    )
    return out


def compute_driver_fuel_forecast_standalone(
    *,
    planning_date: date | None,
    miles: float,
    tractor_mpg: float | None,
    fuel_type: FuelPref,
    driver_timezone: str = "UTC",
) -> dict[str, Any]:
    """POST /eia/driver-fuel-forecast — miles supplied explicitly (no leg geometry)."""
    mr = SimpleNamespace(
        planning_date=planning_date,
        driver_timezone=driver_timezone,
        tractor_mpg=tractor_mpg,
        fuel_type_preference=fuel_type,
        miles_override_today=miles,
    )
    return driver_daily_fuel_forecast([], mr)

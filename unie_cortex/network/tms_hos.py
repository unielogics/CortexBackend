"""
US CMV hours-of-service (simplified engineering model for planning).

**Property-carrying (default):** after ``off_duty_hours_reset`` consecutive hours off,
the driver may drive up to ``max_driving_hours`` within a
``max_on_duty_window_hours`` wall-clock window; a ``break_hours`` off-duty break is
required after ``max_drive_before_break_hours`` of driving. This mirrors the
common 11 / 14 / 10 + 30-minute-after-8 pattern used for property CMV planning
(not a legal audit substitute).

**Passenger-carrying:** 10-hour driving limit within a 15-hour on-duty window,
with 8 consecutive hours off duty to reset (FMCSA passenger rules, simplified).

The 14-hour (or 15-hour) window advances with wall time regardless of short
off-duty breaks; only the long reset starts a fresh window.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any


@dataclass(frozen=True)
class HosRules:
    max_driving_hours: float
    max_on_duty_window_hours: float
    off_duty_hours_reset: float
    break_hours: float
    max_drive_before_break_hours: float
    profile: str


def rules_for_profile(profile: str) -> HosRules:
    if profile == "PASSENGER_CMV":
        return HosRules(
            max_driving_hours=10.0,
            max_on_duty_window_hours=15.0,
            off_duty_hours_reset=8.0,
            break_hours=0.5,
            max_drive_before_break_hours=8.0,
            profile=profile,
        )
    return HosRules(
        max_driving_hours=11.0,
        max_on_duty_window_hours=14.0,
        off_duty_hours_reset=10.0,
        break_hours=0.5,
        max_drive_before_break_hours=8.0,
        profile="PROPERTY_CMV",
    )


def simulate_hos_arrival(
    anchor: datetime,
    *,
    drive_then_dwell_hours: list[tuple[float, float]],
    rules: HosRules,
    max_iterations: int = 50_000,
    initial_drive_in_window: float = 0.0,
    initial_drive_since_break: float = 0.0,
) -> dict[str, Any]:
    """
    ``drive_then_dwell_hours``: for each stop leg, (hours driving to reach stop,
    hours on-duty dwell after arrival). First tuple is from trip start (e.g. domicile)
    to first stop.

    Returns final wall-clock time, break/rest totals, and per-leg arrival timestamps.
    """
    t = anchor
    window_start = anchor
    drive_in_window = max(
        0.0,
        min(float(initial_drive_in_window), rules.max_driving_hours),
    )
    drive_since_break = max(
        0.0,
        min(float(initial_drive_since_break), rules.max_drive_before_break_hours),
    )
    total_off_duty_short_break = 0.0
    total_off_duty_long_reset = 0.0
    leg_arrival_times: list[datetime] = []
    iterations = 0

    for drive_h, dwell_h in drive_then_dwell_hours:
        rem_drive = max(0.0, float(drive_h))
        while rem_drive > 1e-6:
            iterations += 1
            if iterations > max_iterations:
                return {
                    "status": "error",
                    "message": "hos_simulation_iteration_limit",
                    "final_utc": t.isoformat(),
                }

            wall_h = (t - window_start).total_seconds() / 3600.0
            if wall_h >= rules.max_on_duty_window_hours - 1e-9:
                t += timedelta(hours=rules.off_duty_hours_reset)
                total_off_duty_long_reset += rules.off_duty_hours_reset
                window_start = t
                drive_in_window = 0.0
                drive_since_break = 0.0
                continue

            if drive_since_break >= rules.max_drive_before_break_hours - 1e-9:
                t += timedelta(hours=rules.break_hours)
                total_off_duty_short_break += rules.break_hours
                drive_since_break = 0.0
                continue

            room_11 = rules.max_driving_hours - drive_in_window
            room_14 = rules.max_on_duty_window_hours - wall_h
            room_8 = rules.max_drive_before_break_hours - drive_since_break
            chunk = min(rem_drive, room_11, room_14, room_8)
            if chunk < 1e-6:
                if room_8 < 1e-3:
                    t += timedelta(hours=rules.break_hours)
                    total_off_duty_short_break += rules.break_hours
                    drive_since_break = 0.0
                else:
                    t += timedelta(hours=rules.off_duty_hours_reset)
                    total_off_duty_long_reset += rules.off_duty_hours_reset
                    window_start = t
                    drive_in_window = 0.0
                    drive_since_break = 0.0
                continue

            t += timedelta(hours=chunk)
            rem_drive -= chunk
            drive_in_window += chunk
            drive_since_break += chunk

        if dwell_h > 1e-6:
            t += timedelta(hours=float(dwell_h))
            wall_h = (t - window_start).total_seconds() / 3600.0
            if wall_h >= rules.max_on_duty_window_hours - 1e-9:
                t += timedelta(hours=rules.off_duty_hours_reset)
                total_off_duty_long_reset += rules.off_duty_hours_reset
                window_start = t
                drive_in_window = 0.0
                drive_since_break = 0.0

        leg_arrival_times.append(t)

    return {
        "status": "complete",
        "final_utc": t,
        "leg_arrival_utc": leg_arrival_times,
        "total_off_duty_short_break_hours": round(total_off_duty_short_break, 4),
        "total_off_duty_long_reset_hours": round(total_off_duty_long_reset, 4),
        "hos_rules": {
            "profile": rules.profile,
            "max_driving_hours": rules.max_driving_hours,
            "max_on_duty_window_hours": rules.max_on_duty_window_hours,
            "off_duty_hours_reset": rules.off_duty_hours_reset,
            "break_hours": rules.break_hours,
            "max_drive_before_break_hours": rules.max_drive_before_break_hours,
        },
    }

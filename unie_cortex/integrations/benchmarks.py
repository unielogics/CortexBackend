"""Industry context bands for labor throughput (qualitative, not client-specific)."""


def labor_benchmark_context(picks_per_hour_observed: float | None) -> dict:
    """WERC/MHI-style rough bands for narrative only."""
    if picks_per_hour_observed is None:
        return {
            "band": "unknown",
            "note": "Insufficient task timestamps to compare to industry bands.",
        }
    if picks_per_hour_observed < 40:
        return {
            "band": "below_typical",
            "typical_range_lines_per_hour": "80–150+ depending on automation",
            "note": "Observed rate is below common manual pick benchmarks; validate zone mix and data quality.",
        }
    if picks_per_hour_observed < 80:
        return {
            "band": "low_mid",
            "typical_range_lines_per_hour": "80–150+",
            "note": "Room for wave/batch and slotting improvements.",
        }
    return {
        "band": "competitive",
        "note": "Throughput appears within a plausible range; still compare to site SLA targets.",
    }

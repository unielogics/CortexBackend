"""Zone-based exclusion for complementary mock DCs vs audited primary origin (planning mocks only)."""

from __future__ import annotations

from unie_cortex.network.zones import CarrierCode, mock_zone_id, normalize_zip5


def postal_equal(a: str | None, b: str | None) -> bool:
    """True if same 5-digit normalized ZIP."""
    na, nb = normalize_zip5(a or ""), normalize_zip5(b or "")
    return bool(na and nb and na == nb)


def zone_from_origin_to_point(
    origin_postal: str,
    point_postal: str,
    carrier: CarrierCode,
) -> tuple[int, str]:
    """Parcel zone mock from primary hub to candidate location or customer dest."""
    return mock_zone_id(carrier, origin_postal, point_postal)


def is_candidate_too_close_to_origin(
    origin_postal: str,
    candidate_dc_postal: str,
    *,
    carrier: CarrierCode,
    max_easy_zone: int,
) -> bool:
    """
    Exclude complementary DCs that sit in the same or \"easy-reach\" parcel zone bucket
    from the audited origin (mock carrier zone: low integer = geographically close).

    If zone(origin -> candidate) <= max_easy_zone, the candidate is **not** allowed.
    """
    z, _ = zone_from_origin_to_point(origin_postal, candidate_dc_postal, carrier)
    return z <= max(0, int(max_easy_zone))


def is_destination_in_region_for_primary(
    origin_postal: str,
    dest_postal: str,
    *,
    carrier: CarrierCode,
    in_region_max_zone: int,
) -> bool:
    """Customer destinations with zone <= threshold are treated as primary-hub natural region."""
    z, _ = zone_from_origin_to_point(origin_postal, dest_postal, carrier)
    return z <= max(0, int(in_region_max_zone))


def filter_complement_candidates(
    origin_postal: str,
    pool: list[dict],
    *,
    carrier: CarrierCode,
    max_easy_zone: int,
) -> list[dict]:
    """Return pool entries whose ``postal`` is not identical to origin and not zone-excluded."""
    out: list[dict] = []
    for w in pool:
        p = (w.get("postal") or "").strip()
        if not p:
            continue
        if postal_equal(origin_postal, p):
            continue
        if is_candidate_too_close_to_origin(origin_postal, p, carrier=carrier, max_easy_zone=max_easy_zone):
            continue
        out.append(w)
    return out


def sort_candidates_by_zone_desc(origin_postal: str, candidates: list[dict], carrier: CarrierCode) -> list[dict]:
    """Farthest mock zones first — spreads nationwide complements."""
    scored: list[tuple[int, dict]] = []
    for w in candidates:
        p = (w.get("postal") or "").strip()
        if not p:
            continue
        z, _ = zone_from_origin_to_point(origin_postal, p, carrier)
        scored.append((z, w))
    scored.sort(key=lambda x: -x[0])
    return [w for _, w in scored]

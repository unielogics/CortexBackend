"""Resolve ship-from ZIP to a canonical warehouse id using engagement candidate list."""

from __future__ import annotations

from typing import Any

from unie_cortex.network.zones import normalize_zip5


def _zip5(s: str | None) -> str | None:
    if not s:
        return None
    z = normalize_zip5(str(s).strip())
    return z if z and len(z) >= 5 else None


def match_origin_postal_to_warehouse_id(
    origin_postal: str | None,
    candidate_warehouses: list[dict[str, Any]] | None,
) -> str | None:
    """
    Match label origin ZIP to the first candidate with same ZIP5, else same ZIP3 if unique.
    Candidate shape: { "id": str, "postal": str, ... }.
    """
    if not candidate_warehouses:
        return None
    oz = _zip5(origin_postal)
    if not oz:
        return None
    z3 = oz[:3]
    exact: list[str] = []
    z3_matches: list[str] = []
    for c in candidate_warehouses:
        wid = str(c.get("id") or "").strip()
        if not wid:
            continue
        cz = _zip5(c.get("postal"))
        if cz == oz:
            exact.append(wid)
        elif cz and cz[:3] == z3:
            z3_matches.append(wid)
    if len(exact) == 1:
        return exact[0]
    if exact:
        return exact[0]
    if len(z3_matches) == 1:
        return z3_matches[0]
    return None

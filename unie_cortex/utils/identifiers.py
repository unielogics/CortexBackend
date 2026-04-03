"""ASIN / UPC normalization aligned with CortexFrontend `identifierKind.js`."""

from __future__ import annotations

import re

_ASIN_RE = re.compile(r"^[A-Z0-9]{10}$")
_UPC_LENS = frozenset({8, 12, 13, 14})


def compact_identifier_input(raw: str) -> str:
    """Strip, then remove ASCII spaces and hyphens (same as frontend normalize path)."""
    s = (raw or "").strip()
    return re.sub(r"[\s-]+", "", s)


def normalize_asin_filter_param(raw: str) -> str:
    """
    Return canonical uppercase ASIN or raise ValueError.
    Mirrors inferIdentifierKind ASIN branch (10 alphanumeric after compact).
    """
    c = compact_identifier_input(raw)
    c = "".join(ch for ch in c if ch.isalnum()).upper()
    if len(c) != 10 or not _ASIN_RE.match(c):
        raise ValueError("filter_asin must be a 10-character alphanumeric ASIN")
    return c


def normalize_upc_filter_param(raw: str) -> str:
    """
    Return digits-only UPC/EAN or raise ValueError.
    Accepts lengths 8, 12, 13, 14 (frontend UPC rules).
    """
    c = compact_identifier_input(raw)
    digits = "".join(ch for ch in c if ch.isdigit())
    if len(digits) not in _UPC_LENS:
        raise ValueError("filter_upc must be 8, 12, 13, or 14 digits")
    return digits


def _cell_asin_candidate(cell: str) -> str | None:
    c = compact_identifier_input(cell if isinstance(cell, str) else str(cell or ""))
    alnum = "".join(ch for ch in c if ch.isalnum()).upper()
    if len(alnum) == 10 and _ASIN_RE.match(alnum):
        return alnum
    return None


def _cell_upc_candidate(cell: str) -> str | None:
    c = str(cell or "")
    digits = "".join(ch for ch in c if ch.isdigit())
    if len(digits) in _UPC_LENS:
        return digits
    return None


def cell_matches_product_filters(
    cell: str,
    *,
    filter_asin: str | None,
    filter_upc: str | None,
) -> bool:
    if filter_asin:
        cand = _cell_asin_candidate(cell)
        if cand == filter_asin:
            return True
    if filter_upc:
        cand = _cell_upc_candidate(cell)
        if cand == filter_upc:
            return True
    return False


def order_line_raw_row_matches_filters(
    raw_row: dict[str, str],
    *,
    filter_asin: str | None,
    filter_upc: str | None,
) -> bool:
    """True if any CSV cell (including unmapped columns) matches the active filters."""
    if not filter_asin and not filter_upc:
        return True
    for v in raw_row.values():
        if v is None:
            continue
        if cell_matches_product_filters(str(v), filter_asin=filter_asin, filter_upc=filter_upc):
            return True
    return False


def mapped_sku_matches_product_filters(
    sku: str | None,
    *,
    filter_asin: str | None,
    filter_upc: str | None,
) -> bool:
    """True if canonical mapped sku equals an ASIN or UPC filter (e.g. sku column holds ASIN)."""
    if not filter_asin and not filter_upc:
        return True
    s = (str(sku).strip() if sku is not None else "") or ""
    if not s:
        return False
    if filter_asin:
        cand = _cell_asin_candidate(s)
        if cand == filter_asin:
            return True
    if filter_upc:
        cand = _cell_upc_candidate(s)
        if cand == filter_upc:
            return True
    return False

"""Bucket SKUs by rounded weight + dimensions for intelligence inheritance."""

from __future__ import annotations

from typing import Any

from unie_cortex.config import settings


def _bin(val: float | None, step: float) -> str:
    if val is None or step <= 0:
        return "na"
    try:
        x = float(val)
        b = round(x / step) * step
        return str(int(b)) if b == int(b) else f"{b:.2f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return "na"


def physical_signature(
    weight_lb: float | None,
    length_in: float | None,
    width_in: float | None,
    height_in: float | None,
    *,
    weight_step: float | None = None,
    dim_step: float | None = None,
) -> str:
    ws = weight_step if weight_step is not None else settings.physical_signature_weight_step_lb
    ds = dim_step if dim_step is not None else settings.physical_signature_dim_step_in
    parts = (
        f"wt{_bin(weight_lb, ws)}",
        f"L{_bin(length_in, ds)}",
        f"W{_bin(width_in, ds)}",
        f"H{_bin(height_in, ds)}",
    )
    return "|".join(parts)


def attach_signature_to_catalog_row(row: dict[str, Any]) -> dict[str, Any]:
    sig = physical_signature(
        row.get("weight_lb"),
        row.get("length_in"),
        row.get("width_in"),
        row.get("height_in"),
    )
    out = dict(row)
    out["physical_signature"] = sig
    return out


def group_catalog_by_signature(catalog_rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    for raw in catalog_rows:
        row = attach_signature_to_catalog_row(raw)
        sig = row["physical_signature"]
        buckets.setdefault(sig, []).append(row)
    return buckets

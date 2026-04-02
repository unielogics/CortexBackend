"""Physical bucketing for rate shopping reuse (~±2 in per dimension, ±6 oz weight)."""

from __future__ import annotations


def _bucket_dim_two_inch(x: float) -> int:
    """Nearest 2-inch bin (min 2) for cache reuse within ~±2 in tolerance."""
    v = max(0.0, float(x))
    b = int(round(v / 2.0)) * 2
    return max(2, b)


def _bucket_weight_lb(weight_lb: float) -> float:
    """Nearest 6 oz (0.375 lb) slab."""
    step = 6.0 / 16.0
    n = round(float(weight_lb) / step)
    return max(step, n * step)


def physical_rate_bucket(
    length_in: float,
    width_in: float,
    height_in: float,
    weight_lb: float,
) -> str:
    """
    Items within ~2 inches on each dimension (2-inch bins) and ~6 oz weight map to the same bucket
    for cached parcel quotes.
    """
    L = _bucket_dim_two_inch(length_in)
    W = _bucket_dim_two_inch(width_in)
    H = _bucket_dim_two_inch(height_in)
    wb = _bucket_weight_lb(weight_lb)
    return f"L{L}W{W}H{H}_WT{wb:.3f}"


def rate_cache_key_parts(
    *,
    tenant_id: str,
    bucket: str,
    origin_postal: str,
    dest_postal: str,
    service_code: str | None,
) -> tuple[str, str]:
    """Returns (normalized_fingerprint, cache_key_sha256_hex)."""
    import hashlib

    o = _norm_zip(origin_postal)
    d = _norm_zip(dest_postal)
    svc = (service_code or "GROUND").strip().upper() or "GROUND"
    fp = f"{tenant_id}|{bucket}|{o}|{d}|{svc}"
    h = hashlib.sha256(fp.encode("utf-8")).hexdigest()
    return fp, h


def normalize_postal_5(z: str) -> str:
    import re

    d = re.sub(r"\D", "", (z or "").strip())[:5]
    if len(d) >= 5:
        return d[:5]
    if len(d) >= 3:
        return d.zfill(5)
    return (d + "00000")[:5]


def _norm_zip(z: str) -> str:
    return normalize_postal_5(z)

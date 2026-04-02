"""Simple in-memory rate limit for integration routes."""

import time
from collections import defaultdict

RATE_WINDOW = 60  # seconds
RATE_MAX = 30  # requests per window per IP (configurable via env later)

_buckets: dict[str, list[float]] = defaultdict(list)


def _clean_bucket(key: str, window: int = RATE_WINDOW) -> None:
    now = time.monotonic()
    cutoff = now - window
    _buckets[key] = [t for t in _buckets[key] if t > cutoff]


def check_rate_limit(identifier: str, max_per_window: int = RATE_MAX, window: int = RATE_WINDOW) -> bool:
    """Return True if allowed, False if rate limited."""
    _clean_bucket(identifier, window)
    if len(_buckets[identifier]) >= max_per_window:
        return False
    _buckets[identifier].append(time.monotonic())
    return True

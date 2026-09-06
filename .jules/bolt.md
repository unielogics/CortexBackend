## 2026-03-30 - Caching ZIP5 Lat/Lon Coordinate Lookups in Warehouse Mock Rate Grid

**Learning:** `_zip5_to_latlon` in `unie_cortex/services/warehouse_mock_rate_grid.py` is called repeatedly during route intelligence and warehouse grid rate shopping. Adding `@functools.lru_cache(maxsize=2048)` to `_zip5_to_latlon` eliminates redundant string normalization (`normalize_zip5`), dictionary lookups, and coordinate jitter calculations, yielding a ~12.7x speedup for repeated ZIP coordinate lookups (latency reduced from ~2.10s to ~0.165s for 800k calls).

**Action:** Whenever a geographic helper function like `_zip5_to_latlon` or `address_lat_lon` is evaluated frequently across repetitive ZIP code queries, apply `@functools.lru_cache` to eliminate redundant calculation overhead in hot loops.

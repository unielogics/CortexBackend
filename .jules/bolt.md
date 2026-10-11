# Bolt's Journal - Critical Learnings

## 2026-03-31 - Fast-Path Validation and Caching for Carrier Zone Mocks
**Learning:** `normalize_zip5` and `mock_zone_id` in `unie_cortex/network/zones.py` are hot-path utilities called heavily across rate grid generation, smart warehouse network routing, and parcel quote mocks. Adding fast-path string checks (skipping regex overhead) and `@functools.lru_cache` yields a ~17x speedup for zone lookups and ~2x overall speedup for parcel quote evaluations.
**Action:** Always check for un-cached hot-path string/postal parsers and apply fast-path digit length checks before regex evaluation.

## 2026-03-30 - Pre-computing geographic coordinates in radians and caching ZIP3 lookups

**Learning:** `nearest_contiguous_state_for_zip3` performs 48 Haversine calculations per call with repeated dict lookups, string formatting, and `math.radians` conversions. Since 3-digit ZIP prefixes only have 1,000 possibilities, pre-computing state hub coordinates in radians as module constants (`_STATE_HUBS_RAD`) and caching results with `@functools.lru_cache(maxsize=1024)` yields a ~4.88x speedup on cold paths and a ~388x speedup on warm paths.

**Action:** When computing geographic distances against a static set of reference hubs or locations, always pre-convert reference hub coordinates to radians at module load and cache the outer lookup function.

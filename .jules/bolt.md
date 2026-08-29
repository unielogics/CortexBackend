## 2025-05-15 - ZIP3 State Mapping Cache
**Learning:** Demand rollup and warehouse placement logic repeatedly maps ZIP3 codes to contiguous US states via Haversine distance to mock hubs. Since there are only 1,000 possible ZIP3s, this is a perfect candidate for a module-level cache.
**Action:** Use a simple dictionary cache for `nearest_contiguous_state_for_zip3` to avoid redundant trigonometric calculations.

## 2025-05-15 - ZIP3 Regex Fast-path
**Learning:** `_zip3` normalization was using `re.sub` for all inputs. In high-volume demand rollups (e.g. 20k+ rows), this adds up.
**Action:** Add a fast-path for 5-digit numeric strings (most common ZIP format) to bypass regex entirely.

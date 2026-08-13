# Bolt's Performance Journal

## 2026-08-13 - [Zip Geo Caching Optimization]
**Learning:** Adding `@lru_cache` to high-frequency deterministic lookup functions like `nearest_contiguous_state_for_zip3` completely bypasses redundant string operations, dictionary lookups, and distance calculations on hot paths, resulting in a dramatic latency reduction. Bounding the cache to `1024` is perfect since there are at most 1,000 distinct ZIP3 codes in the United States, completely preventing memory leaks.
**Action:** Always identify pure lookup functions that operate on bounded inputs (like geographic identifiers, standard category names, or code maps) and utilize `@lru_cache(maxsize=...)` to avoid O(N) comparisons and geometric mathematics.

# Bolt's Journal

## 2025-05-14 - ZIP3 performance optimization
**Learning:** Functions that operate on ZIP3 strings have a bounded input space of 1000 possible values (000-999). Using `@lru_cache` on these functions effectively memoizes the entire domain, providing massive speedups (e.g., 90x for nearest-state lookups) by avoiding repeated haversine calculations. Additionally, `_zip3` parsing is a hot path for CSV ingestion; a simple `len == 5 and isdigit()` fast-path significantly reduces regex overhead for the most common US postal format.
**Action:** Always look for bounded input domains (like ZIP3, ISO years, or known categories) to apply caching or fast-path heuristics in data processing loops.

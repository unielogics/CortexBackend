## 2025-06-12 - [Multi-stage Velocity Optimization]
**Learning:** Combining several "small" optimizations in a data-heavy hot path (like `build_batch_velocity_enrichment`) can result in massive cumulative gains. Specifically:
1. Using `datetime.fromisoformat` fast-path for ISO strings is ~10-15x faster than `strptime`.
2. Eliminating redundant parsing by passing pre-parsed objects between functions avoids O(N) overhead in batch operations.
3. Early loop exits in window calculations (`reversed()` + `break`) provide significant wins when data is chronologically sorted.

**Action:** When refactoring for performance, look for "hidden" redundant passes over the same dataset (e.g., parsing the same rows for both group and batch-wide analysis). Introduce optional `_pre_parsed` parameters to internal analysis functions to enable result reuse.

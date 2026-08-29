## 2025-05-22 - ISO 8601 Parsing and Batch Optimization
**Learning:** Using `datetime.fromisoformat` as a fast-path for ISO 8601 strings is significantly faster (~40x for single strings) than `strptime` loops. Also, refactoring analysis functions to return parsed intermediate data (like `_Line` objects) avoids redundant O(N) parsing and sorting passes in batch operations, yielding a ~7x speedup for `build_batch_velocity_enrichment`.
**Action:** Always prefer `fromisoformat` for ISO dates and look for opportunities to share parsed data between individual and batch analysis functions.

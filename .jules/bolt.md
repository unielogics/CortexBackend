## 2025-05-15 - Consolidating multiple O(N) passes in analysis rollups
**Learning:** Consolidating multiple O(N) passes (sums, rollups, filters) into a single loop over a large dataset (10k+ rows) provides a measurable speedup by reducing iteration overhead and function call stack depth, even if individual operations remain O(N).
**Action:** When performing multiple aggregations or rollups on a shared dataset, look for opportunities to fuse them into a single iteration pass.

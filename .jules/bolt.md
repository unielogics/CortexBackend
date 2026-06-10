## 2025-05-15 - [Velocity Enrichment Optimization]
**Learning:** Consolidating multiple O(N) passes over datasets into a single loop and using `datetime.fromisoformat` as a fast-path for date parsing significantly reduces overhead in batch processing. Sliding window calculations on sorted data are much faster when iterating backwards and exiting early.
**Action:** When implementing batch analysis, always look for opportunities to parse data once and reuse it. Prefer `fromisoformat` over `strptime` for standard ISO strings.

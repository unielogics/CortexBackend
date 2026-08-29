## 2025-05-15 - [Financial Analysis Loop Consolidation]
**Learning:** `analyze_order_financial_facts` previously performed 15+ redundant full-list traversals for various aggregations (totals, rollups, source counts). For large datasets, this creates significant overhead in Python due to the high cost of dictionary access and iteration. Consolidating these into a single pass and allowing sub-helpers to reuse pre-calculated sums avoids O(N * K) scaling where K is the number of distinct metrics.

**Action:** When adding new metrics to batch analysis functions, always integrate them into the existing primary loop rather than adding a new `sum()` or list comprehension.

## 2025-05-15 - [ZIP3-State Memoization]
**Learning:** `nearest_contiguous_state_for_zip3` performs haversine distance calculations across a fixed set of 48 hub destinations. Since the input space is limited to 1000 possible ZIP3 prefixes, calculating this every time for every order row is wasteful. Memoization with a simple dictionary cache reduces these redundant calculations to nearly zero after the first few rows.

**Action:** Use module-level caches for functions that map small, stable input spaces (like ZIP3s or categories) to computed values to avoid expensive re-calculations in hot loops.

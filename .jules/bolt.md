## 2025-05-15 - Order Financial Analysis Loop Consolidation & Date Parsing
**Learning:** Consolidating 20+ O(N) `sum()` passes into a single loop in `analyze_order_financial_facts` provided a massive (~4x) speedup for 10k row datasets. Additionally, using `datetime.fromisoformat` as a fast-path for ISO 8601 strings is ~25x faster than `strptime` in hot loops.
**Action:** Always look for multiple passes over the same dataset and consolidate. Prioritize `fromisoformat` for date parsing when the format is controlled or predictable.

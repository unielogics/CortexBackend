## 2025-05-15 - [Loop Consolidation & Date Parsing Optimization]
**Learning:** Consolidating multiple O(N) passes (sums, counts, groupings) into a single loop and using `datetime.fromisoformat` instead of `strptime` loops can reduce execution time by nearly 50% for order-financial analysis datasets of ~10k rows.
**Action:** Always check for redundant iterations over the same large dataset in 'analyze' functions and prioritize ISO 8601 fast-paths for date parsing.

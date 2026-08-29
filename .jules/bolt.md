## 2025-05-14 - Optimized Order Financial Analysis

**Learning:** `datetime.strptime` is extremely slow when used in a loop with multiple formats, especially in Python versions prior to significant optimizations in 3.11/3.12. Even in 3.12, `datetime.fromisoformat` is much faster for ISO-like strings. Additionally, multiple O(N) passes for simple aggregations (sums, counts, groupings) add up significantly on large datasets (50k+ rows).

**Action:**
1. Always implement a fast-path for date parsing using `fromisoformat` before falling back to a `strptime` format loop.
2. Consolidate multiple list comprehensions and `sum()` calls into a single `for` loop when processing large data collections to reduce iteration overhead.
3. Use optional pre-computed values in helper functions to avoid redundant calculations.

## 2026-03-28 - Consolidated single-pass aggregation and ISO date fast-pathing in Order Financial Facts

**Learning:** `analyze_order_financial_facts` was executing over 20 separate generator expressions and list traversals over input `rows`, combined with redundant `strptime` exception try/catch loops in `_parse_order_datetime`. Consolidating all row aggregations into a single loop pass and adding `@functools.lru_cache(maxsize=4096)` with `datetime.fromisoformat` fast-path for ISO 8601 strings reduced processing time on 10,000 order financial rows from 716ms to 211ms (~3.4x speedup, ~70.5% latency reduction).

**Action:** Look out for multi-pass `sum(...)` generator expressions on large dataset analysis entry points and combine them into single-pass accumulator loops. Always use `datetime.fromisoformat` fast-paths and LRU caching for ISO date strings before falling back to `strptime`.

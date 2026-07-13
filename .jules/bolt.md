## 2025-05-15 - Consolidating passes and fast-path date parsing
**Learning:** Consolidating multiple O(N) passes into a single loop and using `datetime.fromisoformat` instead of `strptime` for ISO strings significantly reduces CPU overhead in hot paths like financial analysis.
**Action:** Always check for redundant iterations over the same dataset and prefer `fromisoformat` for ISO 8601 strings.

## 2025-05-15 - Schema Consistency in Refactoring
**Learning:** When refactoring for performance, it's crucial to maintain the exact output schema (key names) to avoid breaking downstream consumers, even if a name seems redundant (e.g., `sum_` prefix).
**Action:** Explicitly verify output dictionaries against the original implementation's keys after consolidating logic.

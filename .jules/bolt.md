
## 2026-06-03 - [Optimized ISO 8601 Date Parsing]
**Learning:** Using `datetime.fromisoformat` with a string replacement for 'Z' -> '+00:00' provides a robust fast-path for ISO 8601 strings that is ~14x faster than `strptime` loops. Direct string slicing for year extraction is even faster when full validation isn't required.
**Action:** Always prefer `fromisoformat` for ISO strings and string slicing for component extraction (year/month) in performance-critical paths.

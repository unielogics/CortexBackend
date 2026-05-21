## 2025-05-15 - [Optimization] Fast ISO 8601 parsing and single-pass batch processing

**Learning:** `datetime.strptime` is significantly slower than `datetime.fromisoformat` (introduced in Python 3.7 and enhanced in 3.11+). For common ISO 8601 strings, `fromisoformat` can be ~20x faster. Additionally, refactoring batch processing to avoid redundant parsing of the same data across multiple function calls provides a compounded performance benefit.

**Action:** Always prefer `datetime.fromisoformat` as a fast-path for ISO 8601 strings. When processing large datasets, ensure that expensive operations like date parsing are performed only once per record and the results are reused across calculations.

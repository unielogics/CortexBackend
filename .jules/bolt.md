## 2026-03-30 - ISO 8601 Date Parsing Fast Path in Order Financial Velocity
**Learning:** `datetime.strptime` format loops incur significant CPU overhead when processing thousands of ISO 8601 order date strings. Using `datetime.fromisoformat` with trailing 'Z' replaced by `+00:00` provides a ~20x speedup for standard ISO timestamps while gracefully falling back to `strptime` format strings for legacy or custom date formats.
**Action:** Always prefer native `datetime.fromisoformat` as a fast path before falling back to `strptime` loops when parsing bulk ISO-8601 date datasets.

## 2026-03-30 - ISO Date Parsing Fast Path

**Learning:** `datetime.strptime` loops with format trial-and-error are a massive bottleneck when processing order lines. `datetime.fromisoformat` natively parses ISO 8601 strings (after converting `'Z'` to `'+00:00'`) in C speed (~20x faster than `strptime`), avoiding exception handling overhead on standard date inputs.

**Action:** Always attempt `datetime.fromisoformat` as a fast-path for datetime parsing on ISO strings before falling back to `strptime` format loops or regexes.

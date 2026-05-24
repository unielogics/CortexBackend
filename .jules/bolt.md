## 2025-05-15 - ISO 8601 Parsing Fast-Path
**Learning:** `datetime.strptime` is significantly slower than `datetime.fromisoformat` because it interprets format strings at runtime. In Python 3.11+, `fromisoformat` natively handles the 'Z' suffix. For high-volume CSV processing (like order-financial rows), replacing `strptime` loops with `fromisoformat` fast-paths yields a ~6x performance improvement.
**Action:** Always prefer `datetime.fromisoformat(s.replace("Z", "+00:00"))` for ISO 8601 strings. Use `strptime` only as a fallback for non-standard formats.

## 2025-05-15 - Fast-path Date Parsing in Python

**Learning:** `datetime.fromisoformat` is significantly faster (~10x) than `datetime.strptime` with a loop of format strings for ISO 8601 data. Additionally, direct string slicing (e.g., `s[:4]`) for year extraction from ISO strings is much more efficient than regex matching when the string format is predictable.

**Action:** Always prefer `fromisoformat` for ISO 8601 strings. For high-volume date parsing, implement fast-path heuristics (like checking for '-' or '/' at specific indices) before falling back to expensive `strptime` or regex.

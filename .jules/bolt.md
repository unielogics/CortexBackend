## 2025-05-22 - ISO 8601 Date Parsing Optimization
**Learning:** Using `datetime.fromisoformat` as a fast-path for ISO 8601 strings is ~95% faster than `strptime` loops. Truncating strings (e.g., `s[:26]`) before parsing is an anti-pattern that can cause sub-second precision loss and parsing failures with 'Z' suffixes in newer Python versions or different ISO formats.
**Action:** Always prefer `fromisoformat` with `s.replace("Z", "+00:00")` for robust and high-performance date parsing of ISO strings.

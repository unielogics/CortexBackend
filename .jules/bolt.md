## 2025-05-22 - [ISO 8601 Parsing Optimization]
**Learning:** Using `datetime.fromisoformat` as a fast-path for ISO 8601 strings is ~90%+ faster than `strptime` loops. Truncating strings to fixed lengths (e.g., `s[:26]`) is a codebase anti-pattern that can cause sub-second precision loss and parsing failures with 'Z' suffixes.
**Action:** Always prefer `fromisoformat` for ISO strings, replacing 'Z' with '+00:00' for cross-version compatibility, and maintain a fallback to `strptime` only for non-standard formats.

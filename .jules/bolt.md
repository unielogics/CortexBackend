## 2025-05-15 - Date Parsing Performance
**Learning:** Using `datetime.fromisoformat` as a fast-path for ISO 8601 strings is ~95% faster than `strptime` loops and avoids a common codebase anti-pattern of truncating strings (e.g., `s[:26]`) which causes sub-second precision loss and parsing failures with 'Z' suffixes.
**Action:** Always prefer `fromisoformat` for ISO strings and normalize to naive UTC (e.g. `dt.astimezone(timezone.utc).replace(tzinfo=None)`) to maintain consistency with the existing codebase's preference for naive datetimes.

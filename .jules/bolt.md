## 2025-05-22 - Optimized Date Parsing with Fast Paths
**Learning:** Replacing `strptime` loops with `fromisoformat` and fast-path string slicing for common formats (ISO, slashes) yields massive performance gains (~15x) in data-heavy processing paths.
**Action:** Always prefer `fromisoformat` for ISO strings (replacing 'Z' with '+00:00' for compatibility) and use simple string index checks to gate format-specific parsers.

## 2026-06-04 - Optimized Date Parsing and Year Extraction
**Learning:** Using `datetime.strptime` in a loop for common formats like ISO 8601 is a major performance bottleneck. `datetime.fromisoformat` is significantly faster (~90%+). For partial data extraction (like extracting the year), direct string slicing is even faster and avoids the overhead of creating a full datetime object.
**Action:** Prioritize `fromisoformat` fast-paths for date parsing and string slicing for partial extractions in all high-volume data processing paths.

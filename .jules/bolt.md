## 2025-05-23 - ISO 8601 Parsing Fast-Path
**Learning:** `datetime.strptime` is extremely slow when used in a loop with multiple formats. `datetime.fromisoformat` (especially in Python 3.11+) is ~15-20x faster.
**Action:** Always prefer `fromisoformat` as a first attempt for date parsing if the input is likely ISO 8601.

## 2025-05-23 - Batch Data Redundancy
**Learning:** In batch processing services, a single pass for data extraction/parsing is significantly more efficient than multiple passes (one for grouping, one for rollup).
**Action:** Consolidate row processing to parse and structure data once, then distribute to specialized analysis functions.

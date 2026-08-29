## 2025-05-23 - [Date Parsing and Batch Processing Optimization]
**Learning:** `datetime.fromisoformat` is ~15x faster than `strptime` loops for ISO 8601 strings. Redundant parsing of large datasets in batch functions (like parsing the same rows for both group and batch-level metrics) is a significant bottleneck that can be solved by passing pre-parsed data through internal parameters.
**Action:** Use `fromisoformat` fast-paths for date parsing and update analysis functions to accept `_pre_parsed_data` to avoid redundant O(N) operations in batch contexts.

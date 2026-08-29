## 2026-06-14 - [CSV Inference Optimization]
**Learning:** In `unie_cortex/services/csv_column_inference.py`, the `_synonym_rows()` helper created a new list of ~60 tuples for every header processed. This function-scoped allocation and repeated `re.search` on uncompiled patterns were significant overhead.
**Action:** Use module-level constants for data and pre-compile regex patterns. Implement an `O(1)` dictionary lookup for exact matches to further speed up the hot path.

## 2025-05-15 - ISO 8601 Fast-path & Batch Parsing Reuse
**Learning:** Using `datetime.fromisoformat` is ~95% faster than a `strptime` loop for ISO 8601 strings. However, mixing parsing methods can lead to a mix of naive and aware datetimes, causing `TypeError` during sorting.
**Action:** Standardize on naive UTC-representative datetimes when mixing parsing methods to ensure compatibility with sorting and existing naive-based logic. Also, refactor batch processors to parse dates once and pass them down to avoid O(N*M) redundant work.

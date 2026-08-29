## 2025-05-22 - [Optimized Date Parsing and Batch Processing]
**Learning:**  is a significant bottleneck in data-heavy batch processes. Replacing it with a fast-path for  and refactoring to parse data once and reuse it across group-level analyses can provide massive speedups (e.g., ~8x to 20x).
**Action:** Always check for high-frequency date parsing and consolidate redundant O(N) passes into a single pass when processing large datasets in services.
## 2025-05-22 - [Optimized Date Parsing and Batch Processing]
**Learning:** `datetime.strptime` is a significant bottleneck in data-heavy batch processes. Replacing it with a fast-path for `datetime.fromisoformat` and refactoring to parse data once and reuse it across group-level analyses can provide massive speedups (e.g., ~8x to 20x).
**Action:** Always check for high-frequency date parsing and consolidate redundant O(N) passes into a single pass when processing large datasets in services.

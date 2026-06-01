## 2026-06-01 - Optimize order financial velocity parsing
**Learning:** Using `datetime.fromisoformat` is significantly faster than `strptime` loops. However, care must be taken to maintain return-type consistency (naive vs aware) to avoid `TypeError` in downstream comparisons. Refactoring batch processing to avoid redundant parsing (O(N) vs O(2N)) provides a linear speedup proportional to the number of passes eliminated.
**Action:** Always check existing return types of parsing functions and normalize to the common baseline (usually naive UTC in this codebase) when introducing fast-paths.

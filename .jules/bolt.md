## 2026-06-07 - [Order Financial Velocity Optimization]
**Learning:** Significant performance gains can be achieved by avoiding redundant O(N) passes and using fast-path date parsing (fromisoformat) instead of strptime in hot loops. Consistency in datetime awareness (always UTC) is critical to avoid TypeErrors during comparisons.
**Action:** Use pre-parsed data structures and fast-path heuristics for common data formats in future optimizations.

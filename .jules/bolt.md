## 2026-07-01 - [Memoization and Fast-path for ZIP processing]
**Learning:** Functions with a small, finite input space (like ZIP3 prefixes) are perfect candidates for `lru_cache`, providing massive speedups (90x in this case) with minimal code changes. Adding fast-paths for common string formats (like 5-digit ZIPs) can avoid expensive regex overhead in hot loops.
**Action:** Always check if a frequently called function with a limited input domain is missing a cache. Look for regex usage on simple, predictable string patterns that can be handled with direct string methods.

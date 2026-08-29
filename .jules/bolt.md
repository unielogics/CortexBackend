## 2025-05-15 - [ZIP3 Optimization]
**Learning:** `nearest_contiguous_state_for_zip3` performs expensive Haversine calculations and loops over 48 state hubs. Since there are only 1,000 possible ZIP3 prefixes, memoization is highly effective and safe. Additionally, standardizing 5-digit ZIPs via `re.sub` is a common but expensive operation that can be bypassed with a simple `isdigit()` fast-path.
**Action:** Always consider module-level caching for functions with a finite, small input space and high computational cost. Use fast-paths for common string formats to avoid regex overhead.

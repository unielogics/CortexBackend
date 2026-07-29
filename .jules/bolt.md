# Bolt's Performance Optimization Journal

This journal tracks critical performance-related learnings, surprising behaviors, and codebase-specific patterns discovered while optimizing Unie Cortex.

## 2026-04-20 - Geographic Routing Bottleneck
**Learning:** Found that `nearest_contiguous_state_for_zip3` performs expensive on-the-fly trigonometry calculations (Haversine formula with radians conversion, sine, cosine, arcsin, and square root) for 48 state hub destinations on every call. Many database/API components call this function repeatedly in hot loops. By pre-computing the radians, sine, and cosine coordinates of state hubs, and converting the distance comparison to a Spherical Law of Cosines dot product metric, we can completely eliminate trigonometric functions and square roots inside the loop. Adding an LRU cache speeds up repetitive hits to $O(1)$ under a microsecond.
**Action:** Pre-calculate hub angles, optimize distance calculation using the Law of Cosines, and apply `@functools.lru_cache(maxsize=1024)` to geographic state lookups.

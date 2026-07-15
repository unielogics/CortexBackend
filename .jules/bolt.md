## 2025-05-15 - Optimized ZIP3 to State Mapping
**Learning:** For geographic distance calculations against a fixed set of hubs (like 48 state hubs), pre-computing hub coordinates in radians at the module level avoids redundant math.radians conversions and dictionary lookups in hot loops. Adding LRU caching for deterministic lookups with a small input space (ZIP3) provides massive speedups for repeated calls.
**Action:** Always look for small-cardinality input sets that are deterministic and expensive to compute, as they are prime candidates for caching and pre-computation.

# Bolt's Performance Journal

## 2025-02-18 - Init Journal
**Learning:** Initializing journal to satisfy memory and prompt instructions.
**Action:** Always create and maintain this journal file in `.jules/bolt.md`.

## 2026-07-20 - Geographic state-lookup optimization
**Learning:** Calculating distances against static hub coordinates in loops can be heavily optimized using Spherical Law of Cosines (instead of Haversine) and precomputing radian/sin/cos values of hubs at module initialization. Since there are only 1,000 possible 3-digit ZIP3 combinations, wrapping the function with `lru_cache(maxsize=1024)` results in O(1) warm lookups, providing massive compounding performance gains of up to 688x.
**Action:** Precompute static parameters at the module level and use `lru_cache` for low-cardinality deterministic lookups.

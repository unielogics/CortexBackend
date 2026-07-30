# Bolt's Performance Journal

## 2025-02-17 - Pre-computing static geo-coordinates in hot loops
**Learning:** Performing `math.radians` and trigonometric functions (`math.sin`, `math.cos`) repeatedly inside loops for static coordinate sets (such as destination hubs) introduces massive CPU overhead. Switching to the Spherical Law of Cosines and pre-computing module-level coordinate sines and cosines reduces computation to a single dynamic cosine call per hub, while `@functools.lru_cache` yields sub-millisecond lookups for repeated queries.
**Action:** When calculating distances against static reference locations in hot loops, always precompute reference coordinates and trigonometric values at the module level.

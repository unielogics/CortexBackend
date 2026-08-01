# Bolt's Performance Journal

## 2025-02-14 - Map Destination ZIP3 to State (Zip Geo Routing) Optimization
**Learning:** Found that `nearest_contiguous_state_for_zip3` performs an expensive loop over 48 state hubs, calculating geographic distances using math-heavy `haversine` formula involving numerous trigonometry calculations (radians conversion, sine, cosine, arcsine, square root) for every single call. In a batch of 10,000 requests, this hot path consumes nearly 1 second.
**Action:** Precompute hub coordinates (sin, cos of latitude and longitude in radians) at module load time. Use the Spherical Law of Cosines to evaluate coordinate proximity—maximizing the cosine of distance avoids math.asin, math.sqrt, and redundant trig conversions in the search loop. Wrap the function with `@functools.lru_cache(maxsize=1024)` to achieve O(1) performance for repeat ZIP3 lookups.

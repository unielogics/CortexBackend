## 2026-03-08 - [Zip Geolocation State Assignment Optimization]
**Learning:**
1. Caching the outer-facing function with `@lru_cache` is ~3.4x faster for warm-path hits compared to caching an inner-helper, because the outer cache completely bypasses the overhead of entry string cleanup/parsing and regex-like checks.
2. The Spherical Law of Cosines is mathematically identical to the Haversine formula for locating the closest/minimum point out of a list of fixed candidate coordinates on a sphere. Since the cosine of angular distance is monotonic, maximizing the cosine score (using only `sin`, `cos`, and additions) is perfectly equivalent to minimizing spatial distance, while avoiding expensive `asin` and square roots. This alone gives a ~6.7x speedup on cold paths. Combined with caching, warm paths get a ~770x speedup.
**Action:**
Always apply `@lru_cache` to the outermost cleanup function when inputs are finite (e.g. 1000 ZIP3 values), and prefer monotonic cosine/dot-product scoring over full spatial formulas for relative nearest-neighbor calculations.

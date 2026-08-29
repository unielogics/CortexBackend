
## 2025-05-14 - [Geospatial/ZIP3 Optimization]
**Learning:** Functions performing linear searches or distance calculations (like Haversine) over fixed domains (e.g., US ZIP3 prefixes) are ideal candidates for LRU caching. This avoids O(N) overhead on every call during batch processing.
**Action:** Use `@lru_cache(maxsize=1000)` for ZIP3-based lookups to reduce latency from microseconds to nanoseconds.

## 2025-05-14 - [Regex Fast-Pathing]
**Learning:** `re.sub` and other regex operations have significant overhead compared to simple string checks (`len()` and `isdigit()`). In hot loops processing tens of thousands of rows, fast-pathing common formats (like 5-digit ZIPs) can yield measurable improvements.
**Action:** Always check for the most common/simple format using string methods before falling back to complex regex logic.

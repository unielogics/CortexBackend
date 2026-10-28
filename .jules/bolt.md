## 2026-03-31 - Cache FBA fulfillment line audit calculations safely without unhashable Pydantic Settings

**Learning:** Passing Pydantic `Settings` instances into `@functools.lru_cache` functions triggers `TypeError: unhashable type: 'Settings'`. Extracting primitive float/str setting values (`default_w`, `div`, `tier_default`) as cache key arguments allows safe caching of repetitive package dimension calculations without hash failures or bypassing type safety.

**Action:** When adding LRU caching to functions that accept `Settings` or complex config objects, extract primitive scalar settings fields as parameters to the cached helper function.

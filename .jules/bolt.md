# Bolt's Journal

## 2026-07-24 - Object-ID Caching vs Scalar-Tuple Keys & Retaining Original behavior
**Learning:** Caching computed dictionaries using `id(settings)` keys in a global cache dictionary causes memory leaks because integers do not hold weak references, preventing garbage collection of settings or caching stale keys. Additionally, replacing fallback mechanisms (like `getattr` default arguments) and mutating returned keys (like normalized buckets vs original unmodified buckets) in components can lead to regressions in dynamic environments.
**Action:** Always key global caches on simple immutable scalar tuples (e.g. `(model_version, min_item, audit_grade)`) derived from the settings instance instead of `id(settings)`. Always preserve original unmodified keys in inner components dictionary and retain original `getattr` calls with fallbacks to guarantee robust compatibility.

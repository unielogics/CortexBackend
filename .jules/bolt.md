## 2025-05-15 - [Redundant parsing in batch enrichment]
**Learning:** Batch enrichment functions often perform multiple O(N) passes over the same raw data, repeatedly parsing fields like dates. Consolidating into a single pass and passing pre-parsed objects to group-level analysis functions can yield massive (90%+) performance gains.
**Action:** When optimizing batch processing, look for opportunities to parse once and reuse data via optional internal arguments in downstream functions.

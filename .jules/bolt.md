## 2025-05-15 - [Anti-pattern] Repeated local list creation and regex compilation in hot paths
**Learning:** Large constant data structures (like synonym lists) and regex patterns defined within function scopes cause significant overhead if the function is called frequently (e.g., for every column in a large CSV). Pre-compiling regex and using module-level constants, combined with dictionary lookups for exact matches, can provide a 4-5x speedup.
**Action:** Always move static data and regex patterns to module-level constants in services that handle batch processing or frequent lookups.

## 2025-05-15 - [Troubleshooting] Discrepancy between Memory and Codebase
**Learning:** Discovered that some optimizations documented in the agent's memory (e.g., `_ZIP3_STATE_CACHE`) were missing from the actual codebase. This suggests either a regression, a branch mismatch, or that the memory came from a different environment.
**Action:** Always verify the actual state of the codebase before assuming a documented optimization is present. Use `grep` or `read_file` to confirm existence of cached structures or optimized loops.

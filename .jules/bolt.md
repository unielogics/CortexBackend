## 2026-03-31 - Module-level Pre-computation of Static State Demand Baseline

**Learning:** Re-normalizing static raw state percentage maps on every invocation of `contiguous_state_demand_shares_normalized()` causes unnecessary float parsing, dict creation, and list comprehension overhead (~16.6μs per call) on frequent demand prior lookups across order financial and rate grid functions. Pre-computing static normalized shares into a module-level dictionary `_NORMALIZED_CONTIGUOUS_SHARES` and returning `.copy()` bypasses the normalization logic completely while maintaining caller dict immutability, cutting execution latency to ~0.42μs per call (~39.5x speedup).

**Action:** For static baseline data structures or reference weight maps, calculate and store normalized float mappings once at module load time into a constant, returning `.copy()` if callers mutate dictionaries.

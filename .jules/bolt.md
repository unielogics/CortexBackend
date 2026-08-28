
## 2026-03-31 - Pre-compute Static State Demand Share Dict
**Learning:** Functions returning static config/prior dictionaries (like 48-state normalized demand weights) recreate dictionaries, mutate keys, run dict comprehensions, and sum values on every call, taking ~16.8µs. Pre-computing at module load time and returning `.copy()` reduces execution to ~0.42µs (~39.5x speedup) while preserving caller safety.
**Action:** Identify static data structure generation in utility/prior functions and pre-compute module constants with `.copy()` on getter calls.

## 2026-07-14 - Loop Consolidation Risks
**Learning:** When consolidating multiple O(N) passes into a single loop, be extremely careful with aggregate logic that relies on per-row clipping or conditionals (e.g., `sum(max(0, x-y))`). A naive aggregate calculation like `max(0, sum(x)-sum(y))` is mathematically different and will lead to financial inaccuracies.
**Action:** Always verify that per-row logic is preserved exactly within the new consolidated loop.

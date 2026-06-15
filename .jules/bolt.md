## 2025-05-22 - [Optimized CSV Column Inference]
**Learning:** Repeatedly constructing large lists of tuples and compiling/searching regexes inside function calls (especially in loops) is a significant bottleneck for data processing services. Pre-computing these structures at the module level can provide substantial speedups.
**Action:** Always check if constant data used in hot paths can be pre-computed and stored in module-level constants.

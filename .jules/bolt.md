## 2026-03-01 - Avoid `copy.deepcopy` in Hot Request Paths and Beware cProfile Overhead Distortion

**Learning:**
1. In Python request handlers (such as `propose_routes`), using `copy.deepcopy` on freshly constructed dictionaries introduces heavy recursive object traversal overhead (`_deepcopy_dict`, `_deepcopy_list`, `id()`, `get()`). Replacing `copy.deepcopy` with shallow copies `[r.copy() for r in routes_out]` yields a ~100x speedup for the object copy operation and reduces end-to-end endpoint latency by ~28.7% (from 12.70 ms to 9.05 ms per call).
2. `cProfile` tracer overhead heavily distorts recursive Python function call profiling (like `copy.deepcopy`), making it appear disproportionately slower during profiled runs than in native unprofiled execution. Always validate profile observations with isolated wall-clock microbenchmarks (`time.perf_counter()`).

**Action:**
1. Prefer shallow copies (`[x.copy() for x in list]` or `dict.copy()`) when copying internal structures that are freshly generated per request.
2. Cross-verify cProfile output with unprofiled wall-clock benchmarks before committing to an optimization target.

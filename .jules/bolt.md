## 2026-03-31 - Pre-computing Pairwise Comparison Keys in TMS Opportunity Alerts

**Learning:** In nested pairwise comparison functions like `append_parallel_route_alerts`, performing sorting (`sorted()`) and dictionary allocations (`{"destination_region": ..., ...}`) inside the $O(N^2)$ loop creates significant latency overhead as the number of routes grows. Pre-computing sorted shipment ID tuples and route summary dictionaries in an initial $O(N)$ pass reduces operations to $O(N)$ pre-processing and simple array indexing/filtering during comparisons.

**Action:** Whenever implementing or optimizing pairwise route/entity comparisons, hoist key normalization, sorting, and dictionary allocations into an $O(N)$ pre-pass prior to the $O(N^2)$ nested loop.

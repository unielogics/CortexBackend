## 2025-05-18 - Pre-computing Route Data in TMS Parallel Route Alerts

**Learning:** In `append_parallel_route_alerts` (`unie_cortex/network/tms_opportunity_alerts.py`), nested loops over routes were repeatedly sorting `wms_shipment_ids` lists and allocating route summary dictionaries inside the inner loop (an O(N^2) operation with heavy repeated work). Pre-computing sorted shipment ID tuples and route summary dictionaries in a single O(N) pass prior to the comparison loop eliminated redundant sorting and dict allocations, yielding an ~8.7x - 10.7x speedup.

**Action:** Whenever iterating over pairs of objects in a collection to compare or build relational references (e.g., nested loops), hoist property transformations, sorting, and summary dict creations into an initial single-pass mapping phase.

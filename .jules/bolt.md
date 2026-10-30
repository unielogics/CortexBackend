## 2026-07-18 - Pre-resolving Lat/Lon Coordinates in Nearest-Neighbor Traversal

**Learning:** In nearest-neighbor algorithms (like `_delivery_order_nn_from`), calling address resolution functions (`address_lat_lon`) inside the inner `for i, s in enumerate(remaining)` loop resulted in $O(N^2)$ repeated geocode/coordinate lookup executions. Pre-resolving coordinates once into a tuple `(shipment, lat_lon)` prior to the loop eliminated $O(N^2)$ lookups, yielding a 2.1x to 3.1x speedup on delivery ordering.

**Action:** When writing or optimizing greedy spatial traversal routines (NN / TSP heuristics), always pre-resolve point coordinates once before the selection loop.

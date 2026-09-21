## 2026-03-30 - Pre-resolving Lat/Lon Coordinates in Nearest-Neighbor Route Loops
**Learning:** In nearest-neighbor traversal loops (`_delivery_order_nn_from`), calling address resolution helpers (`address_lat_lon`) inside the `while remaining` / `for s in remaining` loop resulted in $O(N^2)$ repeated geocode/lookup calls ($N(N+1)/2$).
**Action:** Always pre-resolve address coordinates once per item (`[(s, address_lat_lon(s.destination_address)) for s in ss]`) before nearest-neighbor traversal loops to reduce lookups from $O(N^2)$ to $O(N)$.

# Network intelligence: mock parcel, state coverage, and demand weighting

This note describes how **placement mock rate grids**, **state-level routing**, and **demand-weighted** outbound expectations interact with allocation and economics.

## 48 contiguous hub destinations

Mock parcel quotes use **one representative ZIP per contiguous U.S. state** (48 states). **Alaska and Hawaii** are excluded from the hub set; their share in the planning prior is folded out of the denominator so **state demand weights sum to 1.0 over the same 48 states** as the hubs.

## N warehouses

The grid builder supports **any number of U.S. warehouse nodes**. Each node is quoted to the destinations it is assigned for the **legacy unweighted leg mean** (distance tie band). Separately, the service computes a **full 48 × N mock cost matrix** to support **min-mock-per-state** primary assignment and demand-weighted metrics.

## State → DC coverage

- **`state_distance_primary_warehouse_id`**: primary DC per state using **haversine distance** and the **midpoint tie band** (legacy reconciliation).
- **`state_demand_primary_warehouse_id`** / **`state_shipping_coverage`**: primary DC per state under **`state_primary_assignment`** — either **`min_mock_parcel`** (lowest mock $ to that state’s hub) or **`distance_tie_band`** (same rule as distance primary). Rows include **alternates**, **mock_parcel_usd_from_primary**, **demand_share**, and a **hot_demand_decile** flag (top ~10% states by weight).

## Demand weights: default vs labels

- **Default**: static **2026-style** prior in `unie_cortex/network/us_state_demand_share.py`, normalized to 48 states (config metadata via `demand_share_metadata()` / `us_state_demand_forecast_*` settings).
- **Labels**: `rollup_label_demand` rolls **dest_postal** to **ZIP3**, maps to state via **`nearest_contiguous_state_for_zip3`**, then **`build_blended_state_demand_weights_from_labels`** mixes label line counts with the default. **`demand_weight_confidence`** is `mostly_default`, `blended`, or `label_heavy` depending on volume vs `label_state_weight_blend_min_lines`.

International or non-US postals do not contribute to the U.S. state rollup; sparse label history keeps the vector close to the prior.

## Legacy vs demand-weighted parcel

- **`mean_mock_parcel_usd_by_warehouse`**: **Unweighted mean** over the legs each warehouse actually quotes in the grid build (distance-assigned legs, then fill to 48). This remains for backward compatibility and suggested inverse-cost shares.
- **`demand_weighted_expected_mock_parcel_usd_network`**:  
  \(\sum_s w_s \cdot C(\text{primary}(s), s)\)  
  where \(w_s\) is the state demand weight and **primary** follows **`state_primary_assignment`**.
- **`demand_weighted_mock_parcel_usd_if_all_from_warehouse`**: same demand mix, **100%** of orders from each candidate DC (single-hub counterfactual on the **same** weights).

**Item intelligence economics** and **fulfillment network comparison** use the demand-weighted network expectation when the grid is complete, and **scale** by the ratio of **allocation-weighted** mock at SKU weight vs grid baseline when per-SKU weight re-means the warehouse legs.

## Coverage vs inventory

**`coverage_vs_inventory_reconciliation`** compares **modeled geographic routing share** (equal per state or **demand-weighted**, depending on grid output) to **normalized allocation shares**. A gap means **optimal last-mile routing** and **where stock sits** may disagree — closing it requires inbound splits, transfers, or share targets, not a math tweak.

## Smart warehouse network alignment

**`recommend_warehouse_network`** scores candidates with the **same label-blended state demand vector** used in item intelligence (plus hot-ZIP3 proxy), so expansion heuristics and parcel lines stay directionally consistent.

## Mock vs live rates

Zones and totals are **mocks** (`network.parcel_mock`), not contracted rates. Use label history and carrier data where available; see **`adjustable_model_inputs`** on **`fulfillment_network_comparison`** / **`item_intelligence_synthesis`** for levers and cross-links to drivers and negotiation suggestions.

## Fully loaded outbound: one line, not two

**`mock_outbound_parcel_usd_per_unit`** is always the **benchmark** (demand-weighted or share-blended mock). **`label_usd_per_unit`** is non-zero only when **`avg_label_amount_usd`** exists on the SKU merge row — that value **replaces** the mock in the **fully loaded total**. When there is no label history, **`label_usd_per_unit`** is **0** and the mock carries the outbound cost (so you are not charged “two labels”).

## Complementary network audit (assessment)

Warehouse audit can synthesize **extra nationwide mock DCs** (from the same regional archetype pool as smart network) to compare **single-hub** vs **multi-origin** parcel proxies on a **capped** set of hot destination ZIP3s.

- **Zone exclusivity (planning mock):** `mock_zone_id` for a configurable carrier (**`COMPLEMENTARY_AUDIT_ZONE_CARRIER`**, default UPS) from the audited primary origin to each candidate DC. Any candidate with **zone ≤ `COMPLEMENTARY_AUDIT_MAX_EASY_ZONE`** is excluded so complements are not in the same “easy-reach” bucket as the hub.
- **In-region split:** Destinations with **zone(origin → dest) ≤ `COMPLEMENTARY_AUDIT_IN_REGION_MAX_ZONE`** are treated as **in-region**; savings math focuses on **out-of-region** demand weights.
- **Gates:** Requires **`NETWORK_INTELLIGENCE_ENABLED`** and **`AUDIT_COMPLEMENTARY_NETWORK_ENABLED`**. Quote volume is capped by **`COMPLEMENTARY_AUDIT_MAX_DESTINATIONS`**; transit bands use **`estimate_ground_transit_days`** (not carrier SLAs).

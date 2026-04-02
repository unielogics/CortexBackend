# Product Research Optimization (PRO)

**Product Research Optimization** is the Unie Cortex system for **product-level information and decision support** when you identify items by **Amazon ASIN** and/or **UPC**. It combines tenant **SKU catalog** data, **Keepa** (marketplace history and demand signals), optional **Selling Partner API** (SP-API) for **UPC → catalog hints** and **fee estimates**, **operational label/task history** (velocity, physical-twin blending), **multi-warehouse placement mocks**, **landed-cost economics**, **fulfillment network comparison**, and optional **NVIDIA cuOpt** overlays — with structured **outputs** (including four product-research surfaces) you can treat as **suggestions** for planning, not legal or tax advice.

**Legacy API path:** the same run is still exposed as `POST .../item-intelligence/run` for backward compatibility.

---

## 1. When to use which identifier

| You have | What to do |
|----------|------------|
| **ASIN** | Put **`asin`** on the catalog row (`PUT .../catalog/items`). The run loads Keepa **per catalog ASIN** (cached `KEEPA_TTL_DAYS`, default 30d). Optional: **`POST /v1/integrations/keepa/product`** for a **standalone** product + demand snapshot without running the full PRO pipeline. |
| **UPC** | Set **`product_research_resolve_upc`** on the **run body** (requires **SP-API** credentials). Cortex calls **Catalog Items** search by UPC to obtain **research hints** (e.g. ASIN candidates); full economics still need catalog SKUs linked to ASINs where possible. |
| **Both** | Catalog ASIN drives Keepa/demand; UPC field adds SP-API catalog context for research. |

Header: **`X-Unie-Tenant-Id`** (or tenant in path) scopes **Keepa cache**, **demand snapshots**, and **catalog**.

---

## 2. Primary HTTP surface (`/v1/operational`)

All under prefix **`/v1/operational/{tenant_id}/...`**.

| Method | Path | Role |
|--------|------|------|
| `PUT` | `/{tenant_id}/catalog/items` | Upsert SKU + **asin**, dims/weight (`weight_lb`, `length_in`, …). |
| `GET` | `/{tenant_id}/catalog/items` | List catalog. |
| `GET` | `/{tenant_id}/catalog/items/by-sku?sku=` | Get one SKU. |
| `POST` | `/{tenant_id}/{warehouse_id}/product-research-optimization/run` | **Preferred** — full **Product Research Optimization** run. |
| `POST` | `/{tenant_id}/{warehouse_id}/item-intelligence/run` | Same handler as above (legacy name). |

**Run body (high level):** `warehouses` (required), optional `lanes`, `hub_warehouse_id`, `refresh_keepa`, `sku_filter`, `warehouse_candidate_pool`, `include_product_research_economics`, `product_research_outputs`, `product_research_resolve_upc` (**UPC**), `engagement_id` (persist network to assessment engagement), **`product_origin_postal`** (US ZIP; also storable on catalog `extra` as `product_origin_postal` / `product_origin_city` / `product_origin_region`), NVIDIA/cuOpt toggles, etc. See OpenAPI **`/docs`** for `ItemIntelligenceRunBody`.

**Response highlights:** `demand_by_sku`, `placement_mock_rate_grids`, `allocation`, `landed_cost_economics`, `fulfillment_network_comparison`, `item_intelligence_synthesis`, `multi_dc_placement_tri_modal`, `product_research_economics`, plus **`views`** / **`meta.pipeline_stages`** / **`maiw_resources`** when produced by the pipeline.

---

## 3. Supporting integrations (`/v1/integrations`)

| Path | Use with PRO |
|------|----------------|
| `POST /keepa/product` | Direct **ASIN** product + demand extract; respects **Keepa** cache TTL. |
| `POST /sp-api/...` | Fees, buy box, catalog-by-UPC — used from PRO when configured (see OpenAPI). |

Env: **`KEEPA_API_KEY`**, **`KEEPA_TTL_DAYS`**, SP-API variables in **`.env.example`** / `Settings`.

---

## 4. Related documentation

- **[CSV and API For Product Placement.md](./CSV%20and%20API%20For%20Product%20Placement.md)** — broader API map (placement, network, assessment).
- **[PRODUCT_MODES.md](./PRODUCT_MODES.md)** — assessment vs live operations; PRO is primarily **Mode 2** (`/v1/operational`).
- **[ENV_FEATURE_MAPPING.md](./ENV_FEATURE_MAPPING.md)** — Keepa and placement tuning keys.
- **[NETWORK_INTELLIGENCE.md](./NETWORK_INTELLIGENCE.md)** — scenario and mock parcel context shared with placement logic.

---

## 5. Naming note

Internal code may still refer to **item intelligence** or **`run_item_intelligence`**; the **product name** for this capability set is **Product Research Optimization**.

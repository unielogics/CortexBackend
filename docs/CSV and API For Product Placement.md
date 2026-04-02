# Unie Cortex — CSV and API for product placement

This guide covers **order-financial CSV** ingestion, **analyze / planning-run** (P&amp;L + multi-warehouse vs single-warehouse scenarios), and the **network / placement** HTTP APIs. It explains what to send, what comes back, and how optional API keys change realism.

*(Former title: API integration guide — same content scope.)*

---

## 1. Is this system ready for API integration?

**Yes, for integration testing and internal/production-style deployments**, with these practical expectations:

| Area | Ready? | Notes |
|------|--------|--------|
| **HTTP surface** | Yes | FastAPI app; OpenAPI at `/docs` and `/openapi.json`. |
| **Authentication** | Optional | If `API_KEY` or `API_KEYS` is set, `/v1/*` and `/portal` require a key (see §2). If unset, routes are open (dev-style). |
| **Persistence** | Yes | **MongoDB** (`MONGODB_URI`) or **SQL** (`DATABASE_URL`, default SQLite file). Pick one; Mongo is preferred when configured. |
| **Order-financial pipeline** | Yes | Create engagement → mapping → upload CSV → analyze → optional planning-run. Documented flow is stable; responses include P&amp;L and fulfillment comparison blocks. |
| **Network intelligence** | Yes (if enabled) | All `/v1/network/*` routes return **404** when `NETWORK_INTELLIGENCE_ENABLED=false`. |
| **Fidelity of “dollars”** | Mixed | **Linehaul/LTL** in scenarios is **mock** unless you plug contracted pricing elsewhere. **Parcel** can be **live** when Shippo (or custom rate-shopping URL) is configured. Treat outputs as **decision support**, not audited freight invoices. |

**Before going live with customers**, align on: auth always on, DB backups, CORS (`CORS_ORIGINS`), rate limits for integration routes, and which keys are required for the product tier you sell.

---

## 2. Base URL, auth, and discovery

- **Default local**: `http://127.0.0.1:8000` (depends on how you run Uvicorn).
- **Interactive docs**: `GET /docs` (Swagger UI), `GET /redoc`.
- **Health**: `GET /health` — basic OK + database mode. `GET /health/deps` — Mongo ping when using MongoDB.
- **Auth** (when `API_KEY` or comma-separated `API_KEYS` is set):
  - Header: `X-API-Key: <key>` **or** `Authorization: Bearer <key>`
  - Query: `?api_key=<key>` (less ideal for logs)
- **Unauthenticated** (always): `/`, `/health`, `/docs`, `/openapi.json`, `/redoc`, and `GET /v1/integrations/capabilities`.

Optional header used in some flows: `X-Unie-Tenant-Id` (tenant scoping for catalog / Keepa persistence).

---

## 3. Do optional API keys make the system “more intelligent”?

**They change data quality and realism; they do not change every endpoint.**

| Credential | What improves when set |
|------------|-------------------------|
| **`SHIPPO_API_KEY`** | **Integrated parcel quotes** (`RateShoppingService`, `compare-v2-integrated`, order-financial **planning-run** parcel legs). Without it, parcel segments fall back to **internal zone mocks** (consistent but not carrier-accurate). `SHIPPO_MOCK_MODE` can force mock behavior even with a key. |
| **Custom rate shopping** (`RATE_SHOPPING_URL` + `RATE_SHOPPING_API_KEY`) | Alternative backend for the same integrated quoting path when wired in code. |
| **SP-API** (`SPAPI_*` / `AMAZON_LWA_*` / AWS signing vars) | **Referral fee category resolution** from Amazon Catalog for real ASINs during **order-financial CSV ingest** (with caching). Without SP-API, resolver falls back toward **Keepa** or **default** bucket — analysis still runs but `referral_fee_source` may show more `default`. |
| **`KEEPA_API_KEY`** | **Catalog / category fallback** for referral resolution; **`POST /v1/integrations/keepa/product`** and demand snapshots. Planning/item flows that use Keepa become meaningful. |
| **Geocoding** (`GEOAPIFY_API_KEY`, `MAPBOX_TOKEN`, or Nominatim) | Better coordinates for geocode integration endpoints; optional depending on features you use. |
| **Address validation** (`GOOGLE_MAPS_API_KEY` or custom validation URL) | `POST /v1/integrations/validate-address` quality. |
| **`CUOPT_NIM_URL` / `CUOPT_API_KEY`** | Optional **multi-DC optimization** (`POST /v1/assessment/multi-dc-preview`); otherwise internal heuristics. |

**Summary:** For **order-financial planning**, the biggest perceptual difference is usually **Shippo (or custom) vs mock parcel**. For **fee realism on ingest**, **SP-API + Keepa** matter. Linehaul in the current scenario stack remains **mock** unless you treat external contract data separately.

Public capability checks (no secrets returned):

- `GET /v1/integrations/capabilities`
- `GET /v1/network/capabilities` (requires network intel enabled; see §5)

---

## 4. Assessment API — ` /v1/assessment`

Core workflow for **engagements** (assessment spine: labels/tasks) and **order financials** (CSV).

### 4.1 Engagements and mapping

| Method | Path | Body / params | Purpose |
|--------|------|----------------|---------|
| `POST` | `/engagements` | `{ "name": "...", "external_ref": null }` | Create engagement; returns `engagement_id`. |
| `GET` | `/engagements/{engagement_id}` | — | Fetch engagement metadata. |
| `PUT` | `/engagements/{engagement_id}/column-mapping` | `{ "mappings": { ... } }` | Save mappings. Same document can include **labels**, **tasks**, and **order_financials** keys (see existing mapping templates). |
| `GET` | `/engagements/{engagement_id}/column-mapping` | — | Latest mapping JSON. |
| `GET` | `/mapping-templates` | — | List starter templates. |
| `POST` | `/engagements/{engagement_id}/suggest-mapping` | `{ "headers": [...] }` | Light header hints from templates. |

### 4.2 Upload CSV

`POST /engagements/{engagement_id}/upload?kind=...`

- **Multipart**: form field `file` = CSV bytes.
- **`kind`**: `labels` | `tasks` | `order_financials`
- Requires the corresponding columns to be mapped first (`labels`/`tasks`/`order_financials` in mapping).

Response: `batch_id`, `kind`, `row_count`.

### 4.3 Audit spine (labels + tasks)

| Method | Path | Notes |
|--------|------|--------|
| `POST` | `/engagements/{engagement_id}/runs?with_narrative=false` | Runs assessment spine; persists artifact. |
| `GET` | `/engagements/{engagement_id}/runs/{run_id}/report` | Full artifact JSON. |
| `POST` | `/engagements/{engagement_id}/runs/{run_id}/narrative` | Generate narrative text. |
| `GET` | `/engagements/{engagement_id}/runs/{run_id}/visualization-data` | Chart-friendly aggregates. |

### 4.4 Order financials (CSV pipeline)

Detailed column semantics: **[ORDER_FINANCIAL_CSV.md](./ORDER_FINANCIAL_CSV.md)**.

| Method | Path | Body | Purpose |
|--------|------|------|---------|
| `POST` | `/engagements/{engagement_id}/order-financials/infer-mapping` | `{ "headers": [...], "sample_rows": [ {...}, ... ] }` | Proposed `order_financials` map + inference notes (then save via `column-mapping`). |
| `POST` | `/engagements/{engagement_id}/order-financials/analyze` | — | Aggregate analysis on **ingested** facts: `totals`, **`full_financial_image`** (revenue, COGS, margins, CSV profit), velocity, demand rollups, `per_asin`, etc. |
| `POST` | `/engagements/{engagement_id}/order-financials/planning-run` | JSON body below | Smart network + **compare-v2-integrated** + **`fulfillment_comparison_{fbm|fba}`** per requested mode. |

**`planning-run` body** (`OrderFinancialPlanningRunBody` — all fields optional except defaults apply):

```json
{
  "fulfillment_modes": ["fbm", "fba"],
  "csv_baseline_fulfillment": "fbm",
  "weight_lb_per_unit": 1.4,
  "length_in": 9,
  "width_in": 7,
  "height_in": 5,
  "max_scenario_qty": 2500,
  "consolidated_linehaul_cost_multiplier": null
}
```

- **`fulfillment_modes`**: subset of `fbm`, `fba`, `mixed` — drives **scenario engine** (warehouse overlays, FBA transport-only guidance).
- **`csv_baseline_fulfillment`**: `fba` | `fbw` | `fbm` — **labels only** for “current channel” copy, e.g. **`Current (FBM)`**. Default internal normalization: `fba` if omitted/invalid.
- **Dims/weight**: synthetic SKU cube for linehaul + parcel quotes when not inferred per line.
- **`max_scenario_qty`**: caps total units fed into the scenario (demand rollup may be below file totals).
- **`consolidated_linehaul_cost_multiplier`**: optional override for **single-warehouse** path linehaul mock only (see `NETWORK_CONSOLIDATED_LINEHAUL_COST_MULTIPLIER` in settings).

**Planning response highlights:**

- `order_analysis_snapshot` — row_count, totals, **`full_financial_image`**, velocity hint.
- `integrated_rate_shopping_effective` — `true` when Shippo-backed quoting is active for integrated scenarios.
- For each mode in `fulfillment_modes`:
  - `scenario_integrated_{mode}` — full scenario: **`multi_warehouse`** / **`single_warehouse`** (plus legacy **`direct`** / **`consolidated`** aliases), **`vocabulary`**, economics, options, FBM financial breakdown when applicable.
  - `fulfillment_comparison_{mode}` — **`baseline_csv`**, **`full_financial_image`**, **`pnl_and_fulfillment_bridge`**, **`alternative_network_scenario`** (multi/single totals + legacy keys), **`vocabulary`**, deltas, FBA policy block when mode is `fba`.

### 4.5 Other assessment routes

- `POST /multi-dc-preview` — body `{ "warehouses": [...], "lanes": [...] }` — NVIDIA cuOpt (when configured) or internal heuristic multi-DC note. **Not** triggered by CSV upload alone.
  - **Warehouses:** include stable `id` and, for geo-backed optimization, `lat` / `lon` per node.
  - **Lanes:** `from_id` / `to_id` warehouse ids; optional `utilization_pct` (and similar hints) feed the heuristic path.
  - **Python helper:** `unie_cortex.services.multi_dc_preview_heuristic.build_multi_dc_preview_body_heuristic(order_lines=[...], primary_warehouse={"id", "lat", "lon", ...})` builds a minimal body from destination ZIP concentration on order lines (approximate; geocode nodes for production scenarios).

- `POST /engagements/{id}/audit-synthesis` — optional JSON flags:
  - `with_ai_recommendations` (bool): when `true`, calls NVIDIA NIM `chat/completions` on a **trimmed** audit JSON and merges structured items under `ai_recommendations` (does not replace deterministic fields). Requires **`NVIDIA_API_KEY`**; see `NIM_BASE_URL` / `NIM_MODEL` in settings.
  - `ai_detail`: `brief` | `full` — controls how much context is sent to NIM when `with_ai_recommendations` is true.
  - For a **fully offline** demo, omit `with_ai_recommendations` or leave `NVIDIA_API_KEY` unset; the spine + `backbone_completeness` + `competitive_kpis` blocks are still returned.

---

## 5. Network API — `/v1/network`

**Guard:** If `NETWORK_INTELLIGENCE_ENABLED=false`, all routes here return **404**.

Typical first call: `GET /v1/network/capabilities` — lists modes and notes.

### 5.1 Quotes and zones

| Path | Body (JSON) | Role |
|------|-------------|------|
| `POST /zones/resolve` | `{ "carrier": "usps", "origin_postal": "...", "dest_postal": "..." }` | Mock zone ID. |
| `POST /quote/parcel` | Carrier + postals + `weight_lb` + optional dims | **Mock** parcel. |
| `POST /quote/parcel-integrated` | `origin_postal`, `dest_postal`, `weight_lb`, optional `service_code` | **Integrated** quote (Shippo / custom / heuristic). |
| `POST /quote/ltl` | weight, dims, `qty` | **Mock** LTL. |
| `POST /quote/ftl` | weight, cube, pallets | **Mock** FTL. |

### 5.2 Scenarios

| Path | Body | Role |
|------|------|------|
| `POST /scenarios/compare` | Legacy single-origin vs LTL receive (see OpenAPI). | Older topology. |
| `POST /scenarios/compare-v2` | `ScenarioCompareV2Body` — `origins`, `receive_nodes`, `destinations`, `qty`, dims, `freight_mode`, optional `fulfillment_mode`, `consolidated_linehaul_cost_multiplier`, etc. | Mock parcel + mock linehaul; **multi-warehouse** vs **single-warehouse** vocabulary in response. |
| `POST /scenarios/compare-v2-integrated` | Same as v2 + `service_code`, `direct_use_integrated`, `consolidated_parcel_use_integrated` | Parcel legs can use **live** quoting when configured. |

**Destination units:** If any destination includes `units`, **every** destination must include `units` and the **sum must equal `qty`**.

### 5.3 Rollups and ops helpers

- `POST /rollup/demand-from-labels` — tenant/warehouse + label-derived demand tiers.
- `POST /rollup/tms-lanes-from-labels` — lane rollup.
- `POST /labor/operator-stats-from-tasks` — task stats.
- `POST /inventory/days-on-hand-signals` — DOH-style signals.
- `POST /allocation/linehaul-split` — split linehaul $ by weight/cube shares.
- `GET /warehouse-pricing-profiles` — mock profile IDs for FBM fee demos.
- `POST /economics/partial-inbound-flow-mock` — partial transfer flow mock.
- `POST /rate-shop/hot-zip-grid` — cached hot-ZIP grid quotes.

---

## 6. Integrations API — `/v1/integrations`

Rate-limited (see `rate_limit_integrations` in settings).

| Path | Purpose |
|------|---------|
| `POST /geocode/postal` | Postal → lat/lon |
| `POST /geocode/forward` | Free-text → lat/lon |
| `POST /validate-address` | Address validation |
| `POST /rate-quote` | Shipment rate detail (RateShoppingService) |
| `POST /keepa/product` | Keepa product + optional demand extract (needs `KEEPA_API_KEY`) |
| `GET /capabilities` | Which backends are configured (**safe to poll**) |

---

## 7. Other routers (short)

| Prefix | Role |
|--------|------|
| `/v1/operational` | Tenant/warehouse facts (`labels`, `tasks`), audit runs, **recommendations** draft/approve/deny. |
| `/v1/operational` (**Product Research Optimization**) | Catalog listing; `POST .../product-research-optimization/run` (legacy: `item-intelligence/run`). See **[PRODUCT_RESEARCH_OPTIMIZATION.md](./PRODUCT_RESEARCH_OPTIMIZATION.md)**. |
| `/v1/maiw` | MAIW query, context preview, proposals. |
| `/portal` | Static UI when `portal/dist` is built and mounted. |

---

## 8. Environment variables (quick reference)

**Core**

- `MONGODB_URI` / `MONGODB_DB` — Mongo path; if unset, SQL via `DATABASE_URL`.
- `API_KEY` or `API_KEYS` — protect `/v1/*` and `/portal`.
- `CORS_ORIGINS` — comma-separated; empty allows `*` in dev.
- `UPLOAD_DIR` — CSV upload storage.
- `NETWORK_INTELLIGENCE_ENABLED` — default true; false disables `/v1/network/*`.

**Parcel / rates**

- `SHIPPO_API_KEY`, `SHIPPO_MOCK_MODE`
- `RATE_SHOPPING_URL`, `RATE_SHOPPING_API_KEY`

**Amazon / ingest intelligence**

- `SPAPI_*`, `AMAZON_LWA_*`, AWS keys, `AMAZON_REGION`, marketplace id fields (see `Settings` in `unie_cortex/config.py`).
- `KEEPA_API_KEY` and related `KEEPA_*` tuning keys.

**Geo / validation**

- `GEOAPIFY_API_KEY`, `MAPBOX_TOKEN`, `GEOCODING_NOMINATIM`
- `GOOGLE_MAPS_API_KEY` (and related address validation URL keys if used)

**Planning / network tuning**

- `NETWORK_CONSOLIDATED_LINEHAUL_COST_MULTIPLIER`
- `SMART_NETWORK_*` — thresholds for auto warehouse count.
- `CUOPT_NIM_URL`, `CUOPT_API_KEY`

---

## 9. Related docs

- [ORDER_FINANCIAL_CSV.md](./ORDER_FINANCIAL_CSV.md) — column mapping, referral resolution, ingest behavior.
- [PRODUCT_RESEARCH_OPTIMIZATION.md](./PRODUCT_RESEARCH_OPTIMIZATION.md) — ASIN/UPC, catalog, full research run, Keepa/SP-API.

---

## 10. Support for your integration checklist

1. Call `GET /health` and `GET /v1/integrations/capabilities` (and `GET /v1/network/capabilities` if you use network).
2. Create engagement → infer + save mapping → upload `order_financials` → `analyze` → `planning-run` with desired `csv_baseline_fulfillment` and `fulfillment_modes`.
3. Set `API_KEY` in staging/production and send it on every client call.
4. Decide whether **Shippo** (or custom rate URL) is required for your SLA on parcel dollars.
5. Treat **linehaul** totals as **mock** unless you document an external contract feed.

This aligns the API contract with what the codebase implements as of the document date; always verify against `/openapi.json` after upgrades.

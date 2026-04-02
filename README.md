# Unie Cortex

Unified **assessment** (pre-conversion audit) and **operational** (live WMS) platform per the Unie AI plan.

## Two product modes

| **Mode 1 — Assessment** | **Mode 2 — Live operations** |
|---------------------------|------------------------------|
| Audit data from **other WMS** (CSV + mapping) + **new UI** | **APIs** ingest live data from **WMS, OMS, TMS, courier** apps |
| **Before/after** analysis: internal ops + **client shipping $** (benchmarks, zones, recoverable band) | Same intelligence on **streaming facts**; **suggestions** with **approve / deny** |
| Primary: `/v1/assessment/*`, portal, `POST /v1/maiw/proposals/draft` + `engagement_id` | Primary: `/v1/operational/*` facts + audit/proposals + **webhooks to your stack** |

Full narrative: **[docs/PRODUCT_MODES.md](docs/PRODUCT_MODES.md)**.

## Stack

- **Audit spine** (deterministic): label cost vs benchmark, throughput/bottlenecks, discrepancies, coverage tiers.
- **Rate shopping**: `RATE_SHOPPING_URL` + key (multi-carrier if API returns `rates[]`), or internal heuristic.
- **Geocoding**: **Geoapify** (if `GEOAPIFY_API_KEY`), else Mapbox, else Nominatim.
- **Rates**: **Shippo** when `SHIPPO_API_KEY` is set; `SHIPPO_MOCK_MODE=true` uses fake quotes (no API calls). Else custom `RATE_SHOPPING_URL` or heuristic.
- **Keepa**: `KEEPA_API_KEY` + `POST /v1/integrations/keepa/product` for Amazon ASIN lookups.
- **Address validation**: **`GOOGLE_MAPS_API_KEY`** → Google Address Validation API (enable API on the key). Optional **`GOOGLE_ADDRESS_VALIDATION_USPS_CASS`**. Fallback: custom `ADDRESS_VALIDATION_URL`.
- **MAIW** (`/v1/maiw`): **(1)** Q&A + integrations + NIM. **(2)** **Operational proposals** — structured **before** (current cost/labor/routing) vs **after** (routing, efficiency, cost actions, **auto_tasks**); **`/proposals/draft` → `/approve` or `/deny`** (not chat-only).
- **NIM narrative**: `NVIDIA_API_KEY` → `integrate.api.nvidia.com` (optional).
- **cuOpt**: `CUOPT_NIM_URL` for multi-DC preview, else heuristic.
- **Portal**: React + Recharts (`portal/`).

## API

| Prefix | Use |
|--------|-----|
| `/v1/assessment/*` | Engagements, mapping, CSV upload, runs, report, visualization, multi-dc preview |
| `/v1/operational/*` | Bulk label/task facts, audit-run, recommendations draft/approve/deny |
| `/v1/maiw/*` | `query`, `proposals/draft` (before/after), `proposals/{id}`, `approve` / `deny`, list by tenant+warehouse |
| `/v1/integrations/*` | `geocode/postal`, `geocode/forward`, `validate-address`, `rate-quote` |
| `/v1/network/*` | Zones (USPS/UPS/FedEx mocks), LTL/FTL mocks, parcel mock + **integrated** quote, **compare / compare-v2 / compare-v2-integrated**, label demand + TMS lane rollups, operator stats, DOH signals, linehaul split — **[docs/NETWORK_INTELLIGENCE.md](docs/NETWORK_INTELLIGENCE.md)** |
| `/v1/operational/{tenant}/catalog/*` | **Product Research Optimization** — SKU catalog (dims/weight/ASIN) + `POST .../product-research-optimization/run` (alias: `item-intelligence/run`): velocity, Keepa demand, optional UPC (SP-API), economics, suggestions — **[docs/PRODUCT_RESEARCH_OPTIMIZATION.md](docs/PRODUCT_RESEARCH_OPTIMIZATION.md)** |

## Run API

```powershell
cd C:\dev\UnieCortex
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
uvicorn unie_cortex.main:app --reload --port 8080
```

- Docs: http://localhost:8080/docs  
- Tests: `pip install -r requirements-dev.txt` then `pytest tests/ -v`

## Portal dev

```powershell
cd portal
npm install
npm run dev
```

Proxy targets API :8080. Production: `npm run build` then serve `portal/dist` via FastAPI at `/portal/`.

## Env

See `.env.example`: Mongo/SQLite, Shippo, Geoapify, `NVIDIA_API_KEY`, etc.

## Docs

- **[docs/PRODUCT_MODES.md](docs/PRODUCT_MODES.md)** — assessment vs live API, data sources, approve/deny.
- **[docs/PRODUCT_RESEARCH_OPTIMIZATION.md](docs/PRODUCT_RESEARCH_OPTIMIZATION.md)** — ASIN/UPC product research, catalog + run + Keepa/SP-API.
- **[docs/NETWORK_INTELLIGENCE.md](docs/NETWORK_INTELLIGENCE.md)** — network scenarios, carrier zones, LTL/pallet mocks (`/v1/network`).

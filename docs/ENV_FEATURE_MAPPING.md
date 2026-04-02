# Environment Variables → Feature Mapping

| Variable | Feature | Required | Default |
|----------|---------|----------|---------|
| `UNIE_CORTEX_ENV` | Environment (development/production) | No | `development` |
| `API_KEY` / `API_KEYS` | API auth; when set, all /v1/* require key | No | (none) |
| `CORS_ORIGINS` | Allowed origins (comma-separated); empty = * | No | `*` |
| `MONGODB_URI` | MongoDB connection | No* | — |
| `MONGODB_DB` | MongoDB database name | No | `unie_cortex` |
| `DATABASE_URL` | SQLite/Postgres when MONGODB_URI unset | No | `sqlite+aiosqlite:///./unie_cortex.db` |
| `UPLOAD_DIR` | CSV upload directory | No | `./uploads` |
| `GEOAPIFY_API_KEY` | Geocoding (primary) | No | — |
| `GEOCODING_MAPBOX_TOKEN` | Geocoding fallback | No | — |
| `GEOCODING_NOMINATIM` | Use Nominatim when no paid geocoder | No | `true` |
| `SHIPPO_API_KEY` | Rate shopping / labels | No | — |
| `SHIPPO_MOCK_MODE` | Fake rates (no Shippo calls) | No | `false` |
| `RATE_SHOPPING_URL` + `RATE_SHOPPING_API_KEY` | Custom rate API (when Shippo unset) | No | — |
| `RATE_SHOP_CACHE_TTL_DAYS` | Reuse cached parcel quotes (bucket + origin/dest) | No | `30` |
| `KEEPA_API_KEY` | Keepa product lookup | No | — |
| `KEEPA_TTL_DAYS` | Per-ASIN Keepa cache TTL (full product JSON) | No | `30` |
| `KEEPA_PRODUCT_OFFERS` | Keepa `product` `offers=` (competition rows; `0` = omit) | No | `20` |
| `KEEPA_PRODUCT_STATS_DAYS` | Keepa `product` `stats=` window (`0` = omit) | No | `90` |
| `KEEPA_PLANNING_MONTHLY_CAP_3P` | Max suggested monthly units when seller unknown (3P planning) | No | `400` |
| `KEEPA_PLANNING_LARGE_VELOCITY_THRESHOLD` | Above this ASIN monthly mid, no small-listing floor (slice + cap only) | No | `800` |
| `KEEPA_PLANNING_BUYBOX_WINNER_CAP` | Cap when request `marketplace_seller_id` matches Keepa buy box seller | No | `1200` |
| `KEEPA_BUYBOX_HISTORY_WINDOW_DAYS` | Days of `buyBoxSellerIdHistory` used for win-% shares | No | `30` |
| `KEEPA_PLANNING_BUYBOX_HISTORY_KNOWN_CAP` | Cap when seller id matches a seller in buy box history | No | `50000` |
| `KEEPA_PLANNING_BUYBOX_FOLLOWER_SIMILARITY_WEIGHT` | Nudge follower-avg planning from optional client vs offer cohort (0=off) | No | `0.18` |
| `SPAPI_*` / `AMAZON_LWA_*` / AWS signing vars | **Product Research Optimization** — UPC catalog hints, SP-API fee estimates when enabled on the run | No | — |
| `PLACEMENT_MOCK_DESTINATIONS_PER_WAREHOUSE` | Mock parcel quotes per DC (default 48 state hubs) | No | `48` |
| `PLACEMENT_MOCK_MIDPOINT_TIE_BAND` | Relative band: shared dest ZIPs for warehouses near midpoint | No | `0.07` |
| `SKU_INHERIT_MIN_LABEL_LINES` | Borrow shipping stats from physical twin below this line count | No | `12` |
| `PHYSICAL_SIGNATURE_WEIGHT_STEP_LB` | Weight bin size for SKU similarity | No | `0.5` |
| `PHYSICAL_SIGNATURE_DIM_STEP_IN` | Dimension bin size (inches) for SKU similarity | No | `1.0` |
| `GOOGLE_MAPS_API_KEY` | Address validation | No | — |
| `GOOGLE_ADDRESS_VALIDATION_USPS_CASS` | Include USPS CASS in validation | No | `true` |
| `ADDRESS_VALIDATION_URL` + `ADDRESS_VALIDATION_API_KEY` | Custom address validator | No | — |
| `NVIDIA_API_KEY` | MAIW / NIM narrative | No | — |
| `AI_OBSERVABILITY_ENABLED` | Persist NIM `chat/completions` metadata when a `CortexStore` is passed | No | `true` |
| `AI_OBSERVABILITY_PREVIEW_MAX_CHARS` | Store truncated prompt/response previews in `ai_invocations` (PII risk) | No | `0` |
| `NIM_MODEL` | NIM model override | No | `nvidia/llama-3.3-nemotron-super-49b-v1` |
| `NIM_BASE_URL` | NIM endpoint override | No | `https://integrate.api.nvidia.com/v1` |
| `CUOPT_NIM_URL` | Custom cuOpt: `POST {url}/optimize` for multi-DC preview | No | — |
| `MULTI_DC_CUOPT_CLOUD_ENABLED` | Multi-DC preview uses `optimize.api.nvidia.com` (needs `CUOPT_API_KEY` or `NVIDIA_API_KEY`) | No | `false` |
| `TMS_NVIDIA_CUOPT_CLOUD_ENABLED` | `propose_routes` appends NVIDIA cloud cuOpt variant | No | `false` |
| `TMS_NVIDIA_CUOPT_MAX_NODES` | Max matrix nodes for TMS-triggered cuOpt job | No | `25` |
| `TMS_NVIDIA_CUOPT_TIME_LIMIT_SECONDS` | cuOpt solver time limit for TMS job | No | `30` |
| `TMS_NVIDIA_CUOPT_POLL_CAP_SECONDS` | Max status poll seconds for TMS cuOpt | No | `120` |
| `TMS_NIM_DISPATCH_SUMMARY_ENABLED` | NIM plain-text summary on `propose_routes` | No | `false` |
| `RATE_LIMIT_INTEGRATIONS` | Max req/min per IP for integrations (0=off) | No | `30` |
| `NETWORK_INTELLIGENCE_ENABLED` | Expose `/v1/network/*` (zones, LTL/parcel mocks, scenarios) | No | `true` |
| `AUDIT_COMPLEMENTARY_NETWORK_ENABLED` | Run `complementary_network_audit` on `POST .../audit-synthesis` (requires network intel) | No | `true` |
| `COMPLEMENTARY_AUDIT_MAX_EASY_ZONE` | Mock zone ceiling to exclude “easy” complementary DCs vs primary | No | `3` |
| `COMPLEMENTARY_AUDIT_IN_REGION_MAX_ZONE` | Mock zone ceiling for in-region vs out-of-region destination split | No | `3` |
| `COMPLEMENTARY_AUDIT_ZONE_CARRIER` | Carrier code for mock zones: `usps` \| `ups` \| `fedex` | No | `ups` |
| `COMPLEMENTARY_AUDIT_MAX_DESTINATIONS` | Max destination ZIP3s quoted per audit | No | `25` |

\* MongoDB preferred; when unset, uses DATABASE_URL (SQLite/Postgres).

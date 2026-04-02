# Order financial CSV pipeline

UnieCortex ingests marketplace order-level financial exports with automatic header detection, optional `other_expenses` rollup, and 2025→2026 fee bridging.

## Mapping payload (engagement)

Store under the same JSON as labels/tasks:

- `order_financials`: `{ "SourceColumn": "canonical_key", ... }`
- `order_financials_other_expense_headers`: `["UnmappedFeeCol", ...]` — explicit columns summed into `other_expenses_usd`

Canonical keys include: `order_external_id`, `order_date`, `email`, `revenue_usd`, `marketplace_fees_usd`, `product_cogs_usd`, `prep_cost_usd`, `inbound_cost_usd`, `total_fees_usd`, `profit_usd`, `quantity`, `line_price_usd`, `asin`, `sku`, `line_title`, `ship_to_city`, `ship_to_state`, `ship_to_postal`, `ship_to_country`, optional `referral_fee_category_override` (free text or bucket keys such as `media`, `jewelry`, `default`), and optional `marketplace_fees_2026_csv_usd`, `total_fees_2026_csv_usd`, `profit_2026_csv_usd` for precomputed 2026 columns.

## Modeled referral fees (2026 rules)

- **Column override wins**: when `referral_fee_category_override` is mapped, that row uses the override bucket (no Catalog call for that line’s category).
- **Otherwise**, ingest resolves each **distinct ASIN** once: cached **SP-API Catalog** item → **Keepa** category chain if SP is unavailable or yields only a default bucket → **default** 15% bucket.
- **Persisted** on each fact: `referral_fees_modeled_usd`, `referral_fee_bucket`, `referral_fee_source`. Bundled CSV `marketplace_fees_usd` remains **audit-only** for P&amp;L comparisons; analysis exposes modeled referral totals and `marketplace − modeled referral` as implied non-referral (mostly FBA).
- **Environment** (SP-API): `SPAPI_REFRESH_TOKEN` (or `AMAZON_LWA_REFRESH_TOKEN` / `AMAZON_SPAPI_REFRESH_TOKEN`), `SPAPI_CLIENT_ID` or `AMAZON_LWA_CLIENT_ID`, `SPAPI_CLIENT_SECRET` or `AMAZON_LWA_CLIENT_SECRET`, `SPAPI_AWS_ACCESS_KEY_ID` or `AMAZON_SPAPI_AWS_ACCESS_KEY_ID`, `SPAPI_AWS_SECRET_ACCESS_KEY` or `AMAZON_SPAPI_AWS_SECRET_ACCESS_KEY`, optional session token `AMAZON_SPAPI_AWS_SESSION_TOKEN`, optional `SPAPI_ROLE_ARN` / `AMAZON_SPAPI_ROLE_ARN`, `SPAPI_MARKETPLACE_ID`, `SPAPI_CATALOG_TTL_DAYS`, `SPAPI_ENDPOINT_HOST`, `SPAPI_REGION`. Optional `AMAZON_REGION` (`na`, `eu`, `fe`) picks default endpoint and signing region when host/region are not set explicitly. **Keepa**: `KEEPA_API_KEY`. **Seller plan**: `AMAZON_SELLER_PROFESSIONAL_PLAN` (default true; when false, modeled referral adds the Individual $0.99/item line).

## APIs (prefix `/v1/assessment`)

- `POST /v1/assessment/engagements/{id}/order-financials/infer-mapping` — body `{ "headers": [...], "sample_rows": [] }`
- `PUT /v1/assessment/engagements/{id}/column-mapping` — include `order_financials` and optional `order_financials_other_expense_headers`
- `POST /v1/assessment/engagements/{id}/upload?kind=order_financials`
- `POST /v1/assessment/engagements/{id}/order-financials/analyze`
- `POST /v1/assessment/engagements/{id}/order-financials/planning-run` — smart network + scenario compare + fulfillment comparison (`csv_baseline_fulfillment`, `fulfillment_modes`, dims, etc.)

Full HTTP reference (auth, network routes, env vars): **[CSV and API For Product Placement.md](./CSV%20and%20API%20For%20Product%20Placement.md)**.

## 2026 model

Configured in `unie_cortex.config.Settings` (`amazon_*` fields). Logic lives in `unie_cortex.network.amazon_fee_model_2026`. Precomputed CSV 2026 columns win over synthetic inflation for 2025-dated orders.

# Audit mock CSVs (500 data rows each)

Files are **501 lines** each (1 header row + **500** data rows), plus `column_mapping.json` for a single engagement.

**Warehouse baseline (parcel origin on labels):** `823 Westfield Ave, Elizabeth NJ 07208` — ZIP **07208** is written as `OriginZip` on `labels.csv` and should match `PUT .../network-context` `candidate_warehouses[].postal` in the UI/API.

**Source of truth (3PL economics):** prioritize **billing + accounting** (WMS billing export and/or GL); hybrid is expected. Order/label/activity files support reconciliation and modeling but do not replace billed revenue and cost.

Regenerate (deterministic RNG seed 42):

```bash
python scripts/generate_audit_mock_fixtures.py --rows 500
```

Optional larger extract:

```bash
python scripts/generate_audit_mock_fixtures.py --rows 2000
```

## Quick API demo (server on `http://127.0.0.1:8080`)

Replace `EID` after step 1.

1. Create engagement: `POST /v1/assessment/engagements` with body `{"name":"Fixture demo"}`.
2. Save mapping: `PUT /v1/assessment/engagements/{EID}/column-mapping` with JSON body = contents of `column_mapping.json`.
3. (Recommended) `PUT .../network-context` with **`candidate_warehouses`** (origin ZIP / warehouse) and **`facility_profile`**: `sqft`, `loading_dock`, `truck_receive_capabilities`, `headcount_reported` — drives capacity and cost-per-fulfillment in `audit-synthesis`.
4. Upload CSVs (multipart field name `file`):
   - `POST .../upload?kind=labels`
   - `POST .../upload?kind=tasks` (optional — most deployments omit; tasks can be **synthesized** from ASN + `order_lines`)
   - `POST .../upload?kind=order_financials`
   - `POST .../upload?kind=asn` — `asn.csv`
   - `POST .../upload?kind=order_lines` — `order_lines.csv`
   - `POST .../upload?kind=billing` — `billing.csv`
   - `POST .../upload?kind=employees` — `employees.csv`
5. Run spine: `POST .../runs` (optional `?with_narrative=true`). Synthetic tasks are ensured **before** the spine when ASN / order lines exist.
6. Unified story: `POST .../audit-synthesis` with body `{}` or `{"run_id":"<from step 5>"}`. Response includes **`current_state.warehouse_intelligence`**: billing-based **estimated cost per fulfillment**, headcount **capacity baseline**, and observed vs baseline throughput where timestamps allow (set `"skip_synthetic_tasks": true` to disable synthesis).
7. Optional: `POST .../synthetic-tasks/rebuild` to refresh synthetic tasks only.
8. Order economics (optional): `POST .../order-financials/analyze` and `POST .../order-financials/planning-run` with your scenario body.

### curl (from repo root)

```bash
EID=$(curl -s -X POST http://127.0.0.1:8080/v1/assessment/engagements -H "Content-Type: application/json" -d "{\"name\":\"Fixture demo\"}" | jq -r .engagement_id)
curl -s -X PUT "http://127.0.0.1:8080/v1/assessment/engagements/$EID/column-mapping" -H "Content-Type: application/json" -d @tests/fixtures/audit/column_mapping.json
curl -s -X PUT "http://127.0.0.1:8080/v1/assessment/engagements/$EID/network-context" -H "Content-Type: application/json" -d "{\"candidate_warehouses\":[{\"id\":\"elizabeth_primary\",\"postal\":\"07208\",\"label\":\"823 Westfield Ave, Elizabeth NJ 07208\"}],\"facility_profile\":{\"sqft\":185000,\"loading_dock\":true,\"truck_receive_capabilities\":\"2 dock doors, levelers\",\"headcount_reported\":42}}"
curl -s -X POST "http://127.0.0.1:8080/v1/assessment/engagements/$EID/upload?kind=labels" -F "file=@tests/fixtures/audit/labels.csv"
curl -s -X POST "http://127.0.0.1:8080/v1/assessment/engagements/$EID/upload?kind=order_financials" -F "file=@tests/fixtures/audit/order_financials.csv"
curl -s -X POST "http://127.0.0.1:8080/v1/assessment/engagements/$EID/upload?kind=asn" -F "file=@tests/fixtures/audit/asn.csv"
curl -s -X POST "http://127.0.0.1:8080/v1/assessment/engagements/$EID/upload?kind=order_lines" -F "file=@tests/fixtures/audit/order_lines.csv"
curl -s -X POST "http://127.0.0.1:8080/v1/assessment/engagements/$EID/upload?kind=billing" -F "file=@tests/fixtures/audit/billing.csv"
curl -s -X POST "http://127.0.0.1:8080/v1/assessment/engagements/$EID/upload?kind=employees" -F "file=@tests/fixtures/audit/employees.csv"
curl -s -X POST "http://127.0.0.1:8080/v1/assessment/engagements/$EID/runs"
curl -s -X POST "http://127.0.0.1:8080/v1/assessment/engagements/$EID/audit-synthesis" -H "Content-Type: application/json" -d "{}"
```

## Data shape

- **labels.csv**: Carrier mix (UPS-heavy), 2024 ship dates; **origin ZIP 07208** (Elizabeth NJ baseline) → mixed US dest zips; charges tuned so label-cost vs benchmark is visible.
- **tasks.csv**: Optional demo file (zone mix, durations); omit in production-style flows — use ASN + `order_lines` for synthetic tasks.
- **order_financials.csv**: Amazon-style columns mapped to canonical order-financial fields; revenue, fees, COGS, profit, qty, dest ZIP.
- **asn.csv**, **order_lines.csv**, **billing.csv**, **employees.csv**: Tier-1 assessment facts (see `column_mapping.json` blocks `asn`, `order_lines`, `billing`, `employees`).

If you once ran the generator from the wrong working directory, duplicate files may exist under `%USERPROFILE%\tests\fixtures\audit\`; safe to delete that folder.

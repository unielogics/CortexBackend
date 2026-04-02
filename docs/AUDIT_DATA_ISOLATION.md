# Audit vs operational data isolation

Prospect assessment data uses `engagement_id` on fact rows (labels, tasks, order financials). Live operational data uses `tenant_id` + `warehouse_id` with `engagement_id` null.

## Query contract

- **Assessment APIs** list facts with `engagement_id=<engagement UUID>` only.
- **Operational APIs** list facts with `tenant_id` and `warehouse_id`. Store implementations **filter `engagement_id IS NULL`** (SQL) or `engagement_id: null` (Mongo) so assessment uploads cannot appear in tenant-scoped reads even if a caller passes the wrong arguments.

## Related code

- [`unie_cortex/db/store.py`](../unie_cortex/db/store.py) — `label_facts_list`, `task_facts_list`, `order_financial_facts_list`
- [`docs/PRODUCT_MODES.md`](PRODUCT_MODES.md) — Mode 1 vs Mode 2

## Synthesis outputs

- [`unie_cortex/services/audit_synthesis.py`](../unie_cortex/services/audit_synthesis.py) — `audit_outcome` JSON for current vs opportunity
- [`POST /v1/assessment/engagements/{id}/audit-synthesis`](../unie_cortex/api/assessment.py) — HTTP entry point

# Unie Cortex — two product modes

This backend supports **two cases** that match how you sell and operate Unie.

---

## Mode 1 — Assessment / audit (new interface)

**Goal:** Pull data from **another WMS** (or spreadsheets), run a **credible audit**, and show **before → after** so prospects and customers see how **internal operations** and **external outcomes** (e.g. **lower shipping cost for their clients**) can improve.

| Aspect | How Cortex supports it |
|--------|-------------------------|
| **Data in** | CSV upload + **column mapping** to canonical fields (`/v1/assessment/*`). Any WMS export that maps to labels/tasks works. |
| **Intelligence** | **Audit spine**: label $ vs benchmark (Shippo/heuristic), throughput/zones, discrepancies, money band. |
| **Before / after** | **`POST /v1/maiw/proposals/draft`** with `engagement_id` → structured **before** (current metrics, gaps) and **after** (routing, labor, cost, auto_tasks). Optional NIM rationale. |
| **Visualization** | Report + visualization endpoints + **portal** (`/portal/`) — your **new UI** sits on top of the same APIs. |
| **External metrics** | Shipping cost to **clients** is reflected via **label facts** (carrier, service, $, lanes). Benchmark vs rate-shop shows **recoverable $** band. |

**Typical flow:** Create engagement → map columns → upload labels/tasks → run audit → view charts/report → draft MAIW proposal → present before/after in your interface → customer approves in your product (or exports PDF).
**Audit data isolation:** [docs/AUDIT_DATA_ISOLATION.md](AUDIT_DATA_ISOLATION.md). **Synthesis:** `POST /v1/assessment/engagements/{id}/audit-synthesis` returns unified `audit_outcome` JSON; `POST .../infer-mapping-nim` proposes column mappings (NIM when enabled, heuristics always).

**APIs (primary):** `/v1/assessment/*`, `/v1/maiw/proposals/*` (with `engagement_id` path via `__assessment__` + engagement id for listing), `/v1/integrations/*` for demos.

---

## Mode 2 — Live operations (API integration)

**Goal:** **WMS, OMS, TMS, courier apps** send **live facts** into Cortex. The system runs **continuous intelligence** and returns **suggestions** that **operations approve or deny** — wired to **your** WMS and adjacent systems, not only a human UI.

| Source | Example facts | Suggested API |
|--------|----------------|---------------|
| **WMS** | Tasks completed, zones, durations, operators | `POST /v1/operational/{tenant}/{warehouse}/facts/tasks` |
| **OMS** | Order/shipment context (often rolled into label lines) | Extend with future event endpoints or map into label/task bulk |
| **TMS / couriers** | Labels: carrier, service, $, weight, origin/dest ZIP | `POST /v1/operational/{tenant}/{warehouse}/facts/labels` |
| **Intelligence** | Fresh spine on live data | `POST .../audit-run` or **`POST /v1/maiw/proposals/draft`** with `tenant_id` + `warehouse_id` + mappings |
| **Approve / deny** | Governance before changing rules/carriers | **`POST /v1/maiw/proposals/{id}/approve|deny`**, plus existing **`/v1/operational/recommendations/*`** |

**Typical flow:** OMS/TMS/courier **webhook or batch job** → POST label + task facts → optional scheduled **proposal draft** → your orchestrator reads `pending` proposals → **manager approves in your admin** or via API → your integration **pushes changes back** to WMS/TMS (Cortex stores the decision + playbook JSON; execution is yours or a future connector).

**APIs (primary):** `/v1/operational/*`, `/v1/maiw/*` (query + proposals), `/v1/integrations/*` (geocode, rates, validation).

**Product Research Optimization (PRO):** catalog + **`POST /v1/operational/{tenant}/{warehouse}/product-research-optimization/run`** (same handler as legacy **`.../item-intelligence/run`**) for **ASIN** (Keepa, catalog) and optional **UPC** (SP-API hints) plus placement economics and structured suggestions. Guide: **[docs/PRODUCT_RESEARCH_OPTIMIZATION.md](PRODUCT_RESEARCH_OPTIMIZATION.md)**.

---

## Shared backbone (both modes)

- Same **audit spine** and **MAIW proposals** shape (before/after).
- Same **tenant_id + warehouse_id** scoping in operational mode; assessments use **engagement_id** (and `__assessment__` / engagement id for proposal lists).
- **NVIDIA/NIM** optional everywhere (narrative + MAIW Q&A + proposal rationale only).

---

## Summary

| | Mode 1 — Assessment | Mode 2 — Live API |
|--|---------------------|-------------------|
| **UX** | New interface / portal on Cortex APIs | Headless; your apps call APIs |
| **Data** | CSV + mapping | WMS / OMS / TMS / courier → facts APIs |
| **Output** | Before/after + visuals + proposals | Same proposals + recommendations + approve/deny |
| **Next step** | Your UI + PDF/export | Your job runner + WMS/TMS write-back |

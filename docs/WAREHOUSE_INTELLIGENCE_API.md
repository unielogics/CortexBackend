# Warehouse Intelligence — HTTP API

This document describes **Warehouse Intelligence**: the **external intelligence contract** implemented in **Unie Cortex** under the `/v1` prefix (pick pathing, labor, placement, billing, UnieWMS execution, outcomes, and proposal governance).

It complements **MAIW** conversational intelligence at `/v1/maiw/*` (Q&A and operational before/after proposals). Warehouse Intelligence focuses on **structured, capability-specific proposals** with a four-variant envelope.

## Naming

- **Product and documentation name:** **Warehouse Intelligence**.
- **Configuration:** `MAIW_FORCE_INTERNAL_ONLY` still controls whether NVIDIA-backed variant branches are skipped (shared env name with other MAIW features).
- **Wire contract id:** responses include `schemaVersion` **`maiw_wh_v1`** (stable identifier for clients and persistence).
- **NVIDIA:** optional enrichment uses **NVIDIA Multi Agent Intelligence Warehouse** and **NVIDIA cuOpt** where relevant.

## Shared vs UnieWMS-only

| Area | Prefix / scope |
|------|----------------|
| Shared multi-tenant capabilities | `/v1/pick-pathing/*`, `/v1/labor/*`, `/v1/placement/*`, `/v1/billing/*`, `/v1/support/*`, `/v1/intelligence/outcomes`, `/v1/metrics/*`, `/v1/proposals/*` |
| UnieWMS-exclusive (assumes Unie export semantics) | `/v1/uniewms/execution/*` |

Shared routes must not require Unie-only fields; optional blocks (e.g. `omsDemandHints`, extensions) can carry richer UnieWMS data.

## Four-variant response

Every Warehouse Intelligence execution route returns a **`WarehouseProposalEnvelope`**:

- **`proposalId`** — correlation for approve/deny, outcomes, and analytics.
- **`capability`** — stable key (e.g. `batch_pick_path`, `uniewms_priority_cutoff`).
- **`meta`** — `tenantId`, `warehouseId`, optional timezone, correlation, value snapshot.
- **`fourVariants`** — object with four branches:

| Key | Role |
|-----|------|
| `original` | Deterministic baseline from payload (what the WMS would do today without new AI). |
| `internal` | Proprietary heuristics (always populated for a successful request). |
| `internalPlusNvidia` | Internal plus NVIDIA enrichment when available. |
| `nvidiaFromScratch` | NVIDIA-led branch from the same inputs. |

Each variant includes `payload`, `confidence`, `provenance`, `status` (`ok` \| `skipped` \| `error` \| `timeout`), and optional `errorDetail`.

If NVIDIA is unavailable, misconfigured, or **`MAIW_FORCE_INTERNAL_ONLY=true`**, NVIDIA-backed variants return **`skipped`** with a reason; the HTTP request still completes with **`original`** and **`internal`**.

## Routes

| Method | Path | Capability key (stored) |
|--------|------|-------------------------|
| POST | `/v1/pick-pathing/batch-optimize` | `batch_pick_path` |
| POST | `/v1/labor/capacity-forecast` | `labor_capacity` |
| POST | `/v1/labor/staffing-recommendation` | `labor_staffing_seasonal` |
| POST | `/v1/uniewms/execution/prioritize-queue` | `uniewms_priority_cutoff` |
| POST | `/v1/uniewms/execution/wave-suggest` | `uniewms_wave_suggest` |
| POST | `/v1/placement/suggest-putaway` | `placement_putaway` |
| POST | `/v1/billing/explain` | `billing_explain` |
| POST | `/v1/billing/anomaly` | `billing_anomaly` |
| POST | `/v1/support/chat` | `support_chat` |
| POST | `/v1/intelligence/outcomes` | (links to existing `proposalId`) |
| GET | `/v1/metrics/acceptance` | Roll-up: `approved`, `denied`, `pending`, rates |
| GET | `/v1/proposals/{proposalId}` | Stored request + four variants + decision fields |
| POST | `/v1/proposals/{proposalId}/approve` | Body: `chosenVariant`, optional `note` |
| POST | `/v1/proposals/{proposalId}/deny` | Body: `reason` |

Query parameters for metrics: `tenantId`, `capability`, `from`, `to` (ISO datetimes).

## Payload schema version

Inbound/outbound models use **`schemaVersion`: `maiw_wh_v1`** on envelope and metrics responses. Request bodies use **camelCase** aliases for JSON (e.g. `tenantId`, `statusTransitionLog`, `checkInSessions`, `hourlyPay`).

## Persistence and learning

- **SQL** (`maiw_wh_proposals`, `maiw_wh_outcomes`) or **MongoDB** (`cortex_maiw_wh_proposals`, `cortex_maiw_wh_outcomes`) depending on `MONGODB_URI`.
- Each proposal stores: full request JSON, **SHA-256 `payloadHash`** of canonical request, four-variant response, optional value snapshot, and decision (`approved` / `denied` / `pending`) with chosen variant and notes.
- **Outcomes**: POST `/v1/intelligence/outcomes` with `proposalId` and optional temporal fields (`startedAt`, `completedAt`, `assigneeId`, `statusTransitionLog`, `extra`).

## Golden fixtures (CI / demos)

Under `tests/fixtures/maiw_warehouse/`:

- `batch_pick_layout_graph.json` — layout graph + stops.
- `prioritize_queue_rich.json` — jobs with `statusTransitionLog`, cutoffs, value snapshot.
- `labor_capacity_rich.json` — employees with `checkInSessions`, `hourlyPay`, `omsDemandHints`.

## Configuration

| Variable | Effect |
|----------|--------|
| `MAIW_FORCE_INTERNAL_ONLY` | When `true`, Warehouse Intelligence skips NVIDIA branches (those variants return `skipped`). |
| `NVIDIA_API_KEY` | Enables NVIDIA narrative **stub** for Warehouse Intelligence (live URL wiring pending). |
| `CUOPT_API_KEY` or `NVIDIA_API_KEY` | Enables cuOpt **stub** for pick sequencing (placeholder until job mapping exists). |

Future alignment: env prefixes **`NVIDIA_MAIW_*`** and **`NVIDIA_CUOPT_*`** when dedicated endpoints are finalized.

## Implementation layout (this repo)

| Path | Role |
|------|------|
| `unie_cortex/maiw_warehouse/schemas.py` | Pydantic v2 contracts (Warehouse Intelligence payloads) |
| `unie_cortex/maiw_warehouse/engines.py` | Original + internal builders |
| `unie_cortex/maiw_warehouse/orchestrator.py` | Four-variant assembly, timeouts |
| `unie_cortex/maiw_warehouse/nvidia_adapters.py` | NVIDIA/cuOpt stubs |
| `unie_cortex/api/maiw_warehouse.py` | FastAPI router (Warehouse Intelligence) |
| `unie_cortex/db/models.py` | `MaiwWhProposal`, `MaiwWhOutcome` (Warehouse Intelligence persistence) |
| `unie_cortex/db/store.py` | CRUD + metrics query |

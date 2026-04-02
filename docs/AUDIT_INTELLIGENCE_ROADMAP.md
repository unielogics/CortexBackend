# Audit intelligence roadmap (phased)

This document tracks **follow-on epics** after complementary multi-node audit v1 (`warehouse_intelligence.complementary_network_audit`). Items are ordered for planning; delivery is not implied by listing.

1. **Closed-loop dollars** — Scenario workbook with assumption sliders → modeled savings band (e.g. P50) plus sensitivity tables.
2. **Versioned audit runs** — Diff KPIs, themes, and AI recommendation items between successive uploads or run IDs.
3. **Trust pack** — One-page methods, data quality scorecard, and explicit split of deterministic modules vs NIM narrative (extend `nim_invocation`-style provenance).
4. **Workflow export** — Prioritized backlog with owner and effort estimates (JSON + CSV) from audit gaps and strategy suggestions.
5. **Invoice line classification** — Assist `fee_code` / GL mapping with a human review loop and training feedback.
6. **Inventory / service tradeoff (lite)** — Split-shipment and safety-stock narrative tables tied to placement mocks.
7. **Peer benchmarks (optional, later)** — Cross-tenant anonymized lane stats; requires governance and opt-in, distinct from same-tenant multi-node audit.

For network mocks and complementary audit flags, see [NETWORK_INTELLIGENCE.md](NETWORK_INTELLIGENCE.md).

import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import CuOptTriModalPanel from "../components/CuOptTriModalPanel.jsx";
import RateShoppingExecutionSummary from "../components/RateShoppingExecutionSummary.jsx";

const tenant = import.meta.env.VITE_DEMO_TENANT || "demo";
const warehouse = import.meta.env.VITE_DEMO_WAREHOUSE || "w1";

function formatPlacement(placement) {
  if (!Array.isArray(placement) || !placement.length) return "—";
  return placement
    .map((p) => `${p.warehouse_id}: ${p.recommended_monthly_units ?? "—"} units/mo`)
    .join(" · ");
}

function Section({ title, subtitle, children }) {
  return (
    <section style={{ marginTop: 28, borderTop: "1px solid #e2e8f0", paddingTop: 18 }}>
      <h2 style={{ margin: "0 0 6px", fontSize: 16 }}>{title}</h2>
      {subtitle ? (
        <p style={{ margin: "0 0 12px", fontSize: 13, color: "#64748b", lineHeight: 1.5 }}>{subtitle}</p>
      ) : null}
      {children}
    </section>
  );
}

function tableBase() {
  return { width: "100%", borderCollapse: "collapse", fontSize: 13 };
}

function formatTransferLegs(line) {
  const legs = line?.transfer_from_hub;
  if (!Array.isArray(legs) || !legs.length) return "—";
  return legs
    .map((l) => {
      const from = l.from_warehouse_id ?? "?";
      const to = l.to_warehouse_id ?? "?";
      const u = l.units ?? l.monthly_flow_units ?? "?";
      const usd = l.est_cost_usd != null ? Number(l.est_cost_usd).toFixed(2) : "?";
      return `${from}→${to}: ${u} u / ~$${usd}/mo`;
    })
    .join(" · ");
}

/** Primary client view: how many units / month per DC from allocation.lines */
function InventoryPlacementTable({ allocation }) {
  const lines = allocation?.lines;
  if (!Array.isArray(lines) || !lines.length) {
    return <p style={{ color: "#64748b" }}>No allocation lines (check catalog demand and ASINs).</p>;
  }
  return (
    <div style={{ overflow: "auto", border: "1px solid #e2e8f0", borderRadius: 8 }}>
      <table style={tableBase()}>
        <thead>
          <tr style={{ background: "#f1f5f9", textAlign: "left" }}>
            <th style={{ padding: 10 }}>SKU</th>
            <th style={{ padding: 10 }}>Monthly demand (units)</th>
            <th style={{ padding: 10 }}>Recommended placement by warehouse</th>
            <th style={{ padding: 10 }}>Hub → spoke (mock)</th>
            <th style={{ padding: 10 }}>Est. monthly inter-DC transfer $</th>
          </tr>
        </thead>
        <tbody>
          {lines.map((line) => (
            <tr key={line.sku} style={{ borderTop: "1px solid #e2e8f0", verticalAlign: "top" }}>
              <td style={{ padding: 10, fontFamily: "monospace" }}>{line.sku}</td>
              <td style={{ padding: 10 }}>{line.monthly_demand_units ?? "—"}</td>
              <td style={{ padding: 10, fontSize: 12, lineHeight: 1.45 }}>{formatPlacement(line.placement)}</td>
              <td style={{ padding: 10, fontSize: 11, lineHeight: 1.45, maxWidth: 320 }}>{formatTransferLegs(line)}</td>
              <td style={{ padding: 10 }}>{line.transfer_cost_est_usd ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p style={{ padding: 10, margin: 0, fontSize: 12, color: "#64748b" }}>
        Hub for this model: <code>{allocation?.hub_warehouse_id ?? "—"}</code>. Shares:{" "}
        {allocation?.warehouse_share_normalized
          ? JSON.stringify(allocation.warehouse_share_normalized)
          : "—"}
        {allocation?.transfer_linehaul_model && (
          <>
            {" "}
            · linehaul model: <code>{allocation.transfer_linehaul_model}</code>
            {allocation.seller_mixed_pallet_linehaul_applied ? " (mixed pallet applied)" : ""}
          </>
        )}
        {allocation?.min_inter_warehouse_transfer_units != null && (
          <>
            {" "}
            · min transfer batch: <strong>{allocation.min_inter_warehouse_transfer_units}</strong> u/mo
          </>
        )}
      </p>
    </div>
  );
}

/** planning_context.package_enrichment_automatic — rows filled from SP-API / Keepa on this run */
function PackageEnrichmentAutomaticTable({ rows }) {
  if (!Array.isArray(rows) || !rows.length) {
    return <p style={{ color: "#64748b", fontSize: 13 }}>No automatic package fills on this run (catalog already had dims, or enrichment disabled).</p>;
  }
  return (
    <div style={{ overflow: "auto", border: "1px solid #e2e8f0", borderRadius: 8 }}>
      <table style={tableBase()}>
        <thead>
          <tr style={{ background: "#f1f5f9", textAlign: "left" }}>
            <th style={{ padding: 8 }}>SKU</th>
            <th style={{ padding: 8 }}>ASIN</th>
            <th style={{ padding: 8 }}>Filled fields</th>
            <th style={{ padding: 8 }}>Source</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={`${r.sku}-${i}`} style={{ borderTop: "1px solid #e2e8f0", verticalAlign: "top" }}>
              <td style={{ padding: 8, fontFamily: "monospace", fontSize: 12 }}>{r.sku ?? "—"}</td>
              <td style={{ padding: 8, fontSize: 12 }}>{r.asin || "—"}</td>
              <td style={{ padding: 8, fontSize: 12 }}>{Array.isArray(r.filled_fields) ? r.filled_fields.join(", ") : "—"}</td>
              <td style={{ padding: 8, fontSize: 12 }}>{r.enrichment_source ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** placement_mock_rate_grids.warehouses_routing_summary */
function WarehousesRoutingSummaryTable({ summary }) {
  if (!Array.isArray(summary) || !summary.length) {
    return <p style={{ color: "#64748b", fontSize: 13 }}>No warehouses_routing_summary (grid may be skipped).</p>;
  }
  return (
    <div style={{ overflow: "auto", border: "1px solid #e2e8f0", borderRadius: 8 }}>
      <table style={tableBase()}>
        <thead>
          <tr style={{ background: "#f1f5f9", textAlign: "left" }}>
            <th style={{ padding: 8 }}>Warehouse</th>
            <th style={{ padding: 8 }}>States (primary)</th>
            <th style={{ padding: 8 }}>Demand share served</th>
            <th style={{ padding: 8 }}>DW mean mock parcel $</th>
          </tr>
        </thead>
        <tbody>
          {summary.map((r) => {
            const states = Array.isArray(r.states_served) ? r.states_served : [];
            const preview = states.slice(0, 14).join(", ");
            const more = states.length > 14 ? ` … +${states.length - 14}` : "";
            return (
              <tr key={r.warehouse_id} style={{ borderTop: "1px solid #e2e8f0", verticalAlign: "top" }}>
                <td style={{ padding: 8, fontFamily: "monospace", fontSize: 12 }}>{r.warehouse_id}</td>
                <td style={{ padding: 8, fontSize: 11, lineHeight: 1.4, maxWidth: 360 }} title={states.join(", ")}>
                  {states.length ? `${preview}${more}` : "—"}
                  {r.states_served_count != null && (
                    <span style={{ color: "#64748b" }}> ({r.states_served_count})</span>
                  )}
                </td>
                <td style={{ padding: 8, fontVariantNumeric: "tabular-nums" }}>{r.demand_share_served ?? "—"}</td>
                <td style={{ padding: 8, fontVariantNumeric: "tabular-nums" }}>
                  {r.demand_weighted_mean_mock_parcel_usd_among_primary_served_states ?? "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** First columns of mock_parcel_usd_by_warehouse_by_state (full matrix is large). */
function MockParcelMatrixSample({ matrix }) {
  if (!matrix || typeof matrix !== "object") return null;
  const wids = Object.keys(matrix);
  if (!wids.length) return null;
  const stateSet = new Set();
  for (const wid of wids) {
    const row = matrix[wid];
    if (row && typeof row === "object") Object.keys(row).forEach((s) => stateSet.add(s));
  }
  const states = Array.from(stateSet).sort().slice(0, 12);
  if (!states.length) return null;
  return (
    <details style={{ marginTop: 12, fontSize: 12 }}>
      <summary style={{ cursor: "pointer", fontWeight: 600 }}>Mock parcel $ sample by state (first 12 states × warehouses)</summary>
      <div style={{ overflow: "auto", marginTop: 8 }}>
        <table style={tableBase()}>
          <thead>
            <tr style={{ background: "#f1f5f9", textAlign: "left" }}>
              <th style={{ padding: 6 }}>Warehouse</th>
              {states.map((st) => (
                <th key={st} style={{ padding: 6, fontSize: 11 }}>
                  {st}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {wids.map((wid) => (
              <tr key={wid} style={{ borderTop: "1px solid #e2e8f0" }}>
                <td style={{ padding: 6, fontFamily: "monospace", fontSize: 11 }}>{wid}</td>
                {states.map((st) => {
                  const v = matrix[wid]?.[st];
                  return (
                    <td key={st} style={{ padding: 6, fontSize: 11, fontVariantNumeric: "tabular-nums" }}>
                      {v != null && typeof v === "number" ? v.toFixed(3) : v ?? "—"}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p style={{ margin: "8px 0 0", fontSize: 11, color: "#64748b" }}>
        Full N×48 matrix is in <code>placement_mock_rate_grids.mock_parcel_usd_by_warehouse_by_state</code> (see raw JSON
        below).
      </p>
    </details>
  );
}

function NetworkAdjustmentNotes({ allocation }) {
  const lines = allocation?.lines || [];
  const withAdj = lines.filter((l) => l.network_placement_adjustment);
  if (!withAdj.length) return null;
  return (
    <ul style={{ margin: "12px 0 0", paddingLeft: 20, fontSize: 13, color: "#92400e", background: "#fffbeb", padding: "12px 12px 12px 28px", borderRadius: 8 }}>
      {withAdj.map((l) => (
        <li key={l.sku} style={{ marginBottom: 6 }}>
          <strong>{l.sku}:</strong> {l.network_placement_adjustment?.rationale || JSON.stringify(l.network_placement_adjustment)}
        </li>
      ))}
    </ul>
  );
}

/** Catalog-wide network scenarios from the same item-intelligence run (not PRO-only). */
function WarehouseNetworkScenariosPanel({ wno, trim, recommendedNetwork }) {
  const opts = wno?.options;
  const hasOpts = Array.isArray(opts) && opts.length > 0;
  const hasTrim = trim && typeof trim === "object" && Object.keys(trim).length > 0 && trim.status !== "skipped";
  const hasRec = recommendedNetwork && typeof recommendedNetwork === "object" && Object.keys(recommendedNetwork).length > 0;

  if (!hasOpts && !hasTrim && !hasRec) {
    return (
      <p style={{ color: "#64748b", fontSize: 13 }}>
        No <code>warehouse_network_recommendation_options</code> yet (or run returned skipped). This block is independent of
        product research economics — it appears whenever the backend attaches network scenarios to the same response.
      </p>
    );
  }

  return (
    <div style={{ display: "grid", gap: 16 }}>
      {typeof wno?.monthly_total_demand_units === "number" && (
        <p style={{ margin: 0, fontSize: 13, color: "#475569" }}>
          Catalog-wide monthly demand (mid sum) for network sizing:{" "}
          <strong>{wno.monthly_total_demand_units}</strong> units/mo ·{" "}
          <code style={{ fontSize: 12 }}>{wno.assumptions_version ?? "—"}</code>
        </p>
      )}

      {hasTrim && (
        <div
          style={{
            fontSize: 13,
            padding: "12px 14px",
            borderRadius: 8,
            border: "1px solid #bae6fd",
            background: "#f0f9ff",
          }}
        >
          <strong>Client warehouse trim</strong>{" "}
          {trim.client_trim_applied ? "(applied)" : "(evaluated, no change)"} —{" "}
          <code>{trim.selected_warehouse_count ?? "—"}</code> DC(s), hub <code>{trim.hub_warehouse_id ?? "—"}</code>
          {Array.isArray(trim.trace) && trim.trace.length > 0 && (
            <ul style={{ margin: "8px 0 0", paddingLeft: 20, fontSize: 12, color: "#0369a1" }}>
              {trim.trace.slice(-4).map((t, i) => (
                <li key={i}>{t}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {hasRec && (
        <details style={{ fontSize: 13 }}>
          <summary style={{ cursor: "pointer", fontWeight: 600 }}>Auto-expanded recommended network (raw)</summary>
          <pre
            style={{
              marginTop: 8,
              background: "#f8fafc",
              border: "1px solid #e2e8f0",
              borderRadius: 8,
              padding: 12,
              fontSize: 11,
              overflow: "auto",
              maxHeight: 220,
            }}
          >
            {JSON.stringify(recommendedNetwork, null, 2)}
          </pre>
        </details>
      )}

      {hasOpts && (
        <div style={{ display: "grid", gap: 12 }}>
          {opts.map((o) => (
            <div
              key={o.option_key}
              style={{
                border: "1px solid #e2e8f0",
                borderRadius: 8,
                padding: "14px 16px",
                background: o.option_key === "multi_dc" && o.feasible === false ? "#fffbeb" : "#fafafa",
              }}
            >
              <div style={{ display: "flex", flexWrap: "wrap", alignItems: "baseline", gap: 8, marginBottom: 8 }}>
                <span style={{ fontWeight: 700, fontSize: 14 }}>{o.label || o.option_key}</span>
                <code style={{ fontSize: 11 }}>{o.option_key}</code>
                <span
                  style={{
                    fontSize: 12,
                    padding: "2px 8px",
                    borderRadius: 999,
                    background: o.feasible ? "#dcfce7" : "#fee2e2",
                    color: o.feasible ? "#166534" : "#991b1b",
                  }}
                >
                  {o.feasible ? "Feasible at stated velocity" : "Not feasible at stated velocity"}
                </span>
                {o.achievable_with_deeper_stocking_for_transfer_moq && (
                  <span
                    style={{
                      fontSize: 12,
                      padding: "2px 8px",
                      borderRadius: 999,
                      background: "#dbeafe",
                      color: "#1e40af",
                    }}
                  >
                    Deeper stocking can clear transfer MOQ
                  </span>
                )}
              </div>
              <p style={{ margin: "0 0 8px", fontSize: 12, color: "#64748b" }}>
                Warehouses: <strong>{o.selected_warehouse_count ?? o.applied_warehouse_count ?? "—"}</strong> · hub{" "}
                <code>{o.hub_warehouse_id ?? "—"}</code>
                {o.target_warehouse_count_requested != null && (
                  <>
                    {" "}
                    · multi target requested: <strong>{o.target_warehouse_count_requested}</strong>
                  </>
                )}
              </p>
              {o.suggested_months_stock_depth_for_hub_spoke_transfer_moq != null && (
                <p style={{ margin: "0 0 8px", fontSize: 13, lineHeight: 1.5 }}>
                  <strong>Suggested months (transfer MOQ):</strong> {o.suggested_months_stock_depth_for_hub_spoke_transfer_moq}
                  {o.approx_catalog_units_over_that_window != null && (
                    <>
                      {" "}
                      (~{o.approx_catalog_units_over_that_window} catalog units over that window at current velocity)
                    </>
                  )}
                </p>
              )}
              {o.client_planning_nudge && (
                <p style={{ margin: "0 0 8px", fontSize: 13, lineHeight: 1.55, color: "#1e293b" }}>{o.client_planning_nudge}</p>
              )}
              {o.infeasibility_note && !o.client_planning_nudge && (
                <p style={{ margin: "0 0 8px", fontSize: 12, color: "#92400e" }}>{o.infeasibility_note}</p>
              )}
              {Array.isArray(o.selected_warehouses) && o.selected_warehouses.length > 0 && (
                <div style={{ overflow: "auto", marginTop: 8 }}>
                  <table style={tableBase()}>
                    <thead>
                      <tr style={{ background: "#f1f5f9", textAlign: "left" }}>
                        <th style={{ padding: 6 }}>id</th>
                        <th style={{ padding: 6 }}>postal</th>
                        <th style={{ padding: 6 }}>share %</th>
                        <th style={{ padding: 6 }}>min moq/mo</th>
                      </tr>
                    </thead>
                    <tbody>
                      {o.selected_warehouses.map((w) => (
                        <tr key={w.id} style={{ borderTop: "1px solid #e2e8f0" }}>
                          <td style={{ padding: 6, fontFamily: "monospace", fontSize: 12 }}>{w.id}</td>
                          <td style={{ padding: 6, fontSize: 12 }}>{w.postal ?? "—"}</td>
                          <td style={{ padding: 6, fontSize: 12 }}>{w.target_share_pct ?? "—"}</td>
                          <td style={{ padding: 6, fontSize: 12 }}>{w.min_monthly_flow_units ?? "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      <details style={{ fontSize: 12 }}>
        <summary style={{ cursor: "pointer" }}>Raw warehouse_network_recommendation_options JSON</summary>
        <pre
          style={{
            background: "#0f172a",
            color: "#e2e8f0",
            padding: 12,
            fontSize: 10,
            overflow: "auto",
            maxHeight: 280,
            marginTop: 8,
            borderRadius: 6,
          }}
        >
          {JSON.stringify(wno ?? {}, null, 2)}
        </pre>
      </details>
    </div>
  );
}

function formatMonthlyUnitsInteger(row) {
  const v = row.monthly_units_est_mid;
  if (v == null || v === "") return row.status ?? "—";
  const n = Number(v);
  if (!Number.isFinite(n)) return String(v);
  return String(Math.round(n));
}

function formatInventoryCoverHint(inv) {
  if (!inv || typeof inv !== "object") return { badge: null, text: "—" };
  if (inv.human_readable_one_liner) return { badge: null, text: inv.human_readable_one_liner };
  const splits = Array.isArray(inv.warehouse_splits) ? inv.warehouse_splits : Array.isArray(inv.splits) ? inv.splits : [];
  if (!splits.length) return { badge: null, text: "—" };
  const parts = splits.map((s) => {
    const wid = s.warehouse_id ?? "?";
    const cov = s.suggested_units_for_target_cover ?? "?";
    const mo = s.allocation_monthly_flow_units;
    const share = s.allocation_share_of_flow;
    if (mo != null && share != null) {
      return `${wid}: ${cov}u @ ${mo}/mo (${(Number(share) * 100).toFixed(1)}% flow)`;
    }
    return `${wid}: ~${cov} u (${s.target_days_cover ?? "?"}d)`;
  });
  const badge =
    inv.cover_split_basis === "allocation_monthly_flow_integer_split" ? (
      <span
        style={{
          fontSize: 10,
          fontWeight: 700,
          padding: "2px 6px",
          borderRadius: 4,
          background: "#dbeafe",
          color: "#1e40af",
          marginRight: 6,
        }}
        title="Cover split from allocation monthly flows (not even divide)"
      >
        allocator cover
      </span>
    ) : null;
  return { badge, text: parts.join(" · ") };
}

function DemandEnrichmentTable({ demandBySku }) {
  const rows = useMemo(() => {
    if (!demandBySku || typeof demandBySku !== "object") return [];
    return Object.entries(demandBySku).map(([sku, d]) => ({ sku, ...(typeof d === "object" && d ? d : {}) }));
  }, [demandBySku]);
  if (!rows.length) return <p style={{ color: "#64748b" }}>No demand_by_sku (add ASINs to catalog).</p>;
  return (
    <div style={{ overflow: "auto", border: "1px solid #e2e8f0", borderRadius: 8 }}>
      <table style={tableBase()}>
        <thead>
          <tr style={{ background: "#f1f5f9", textAlign: "left" }}>
            <th style={{ padding: 10 }}>SKU</th>
            <th style={{ padding: 10 }}>ASIN</th>
            <th style={{ padding: 10 }}>Est. monthly units (integer)</th>
            <th style={{ padding: 10 }}>Reviews (30d)</th>
            <th style={{ padding: 10 }}>Sales rank (30d)</th>
            <th style={{ padding: 10 }}>Inventory / cover (by DC)</th>
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, 60).map((r) => {
            const inv = r.inventory_placement_summary;
            const { badge, text } = formatInventoryCoverHint(inv);
            const mom =
              r.momentum_30d_ux && typeof r.momentum_30d_ux === "object" ? r.momentum_30d_ux : null;
            const rev30 = mom?.new_reviews_last_30d;
            const rankLine =
              mom?.sales_rank_delta_30d_plain_language ||
              (mom?.sales_rank_delta_30d != null ? `Δ ${mom.sales_rank_delta_30d}` : null);
            const regime = mom?.regime ? String(mom.regime) : null;
            return (
              <tr key={r.sku} style={{ borderTop: "1px solid #e2e8f0", verticalAlign: "top" }}>
                <td style={{ padding: 10, fontFamily: "monospace" }}>{r.sku}</td>
                <td style={{ padding: 10 }}>{r.asin || "—"}</td>
                <td style={{ padding: 10, fontVariantNumeric: "tabular-nums" }}>{formatMonthlyUnitsInteger(r)}</td>
                <td style={{ padding: 10, fontSize: 12 }}>
                  {rev30 != null ? String(rev30) : "—"}
                  {regime ? (
                    <div style={{ color: "#64748b", marginTop: 4 }}>{regime}</div>
                  ) : null}
                </td>
                <td style={{ padding: 10, fontSize: 12, lineHeight: 1.45, maxWidth: 280 }}>
                  {rankLine || "—"}
                </td>
                <td style={{ padding: 10, fontSize: 12, lineHeight: 1.45 }}>
                  {badge}
                  {text}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function SynthesisPerSkuCards({ perSku }) {
  if (!Array.isArray(perSku) || !perSku.length) {
    return <p style={{ color: "#64748b" }}>No synthesis.per_sku.</p>;
  }
  return (
    <div style={{ display: "grid", gap: 12 }}>
      {perSku.slice(0, 40).map((row) => {
        const f = row.fulfillment || {};
        const actions = Array.isArray(f.recommended_actions) ? f.recommended_actions.slice(0, 4) : [];
        return (
          <div
            key={row.sku}
            style={{
              border: "1px solid #e2e8f0",
              borderRadius: 8,
              padding: "12px 14px",
              background: "#fafafa",
            }}
          >
            <div style={{ fontFamily: "monospace", fontWeight: 600, marginBottom: 8 }}>{row.sku}</div>
            {f.headline && <p style={{ margin: "0 0 8px", fontSize: 13, lineHeight: 1.5 }}>{f.headline}</p>}
            {f.verdict && (
              <p style={{ margin: "0 0 6px", fontSize: 12, color: "#475569" }}>
                Verdict: <code>{f.verdict}</code>
              </p>
            )}
            {row.placement?.note && (
              <p style={{ margin: "0 0 8px", fontSize: 12, color: "#1e40af" }}>{row.placement.note}</p>
            )}
            {row.allocation_snapshot && (
              <p style={{ margin: "0 0 8px", fontSize: 12, color: "#64748b" }}>
                Demand {row.allocation_snapshot.monthly_demand_units ?? "—"} units/mo · hub{" "}
                {row.allocation_snapshot.hub_warehouse_id ?? "—"} · transfer ${row.allocation_snapshot.transfer_cost_est_usd_month ?? "—"}
                /mo
              </p>
            )}
            {row.economics?.negotiation_priorities?.length > 0 && (
              <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12 }}>
                {row.economics.negotiation_priorities.map((x, i) => (
                  <li key={i}>{x}</li>
                ))}
              </ul>
            )}
            {actions.length > 0 && (
              <ul style={{ margin: "8px 0 0", paddingLeft: 18, fontSize: 12 }}>
                {actions.map((a, i) => (
                  <li key={i}>{a}</li>
                ))}
              </ul>
            )}
          </div>
        );
      })}
    </div>
  );
}

function LandedAndFulfillmentTables({ landed, fnc }) {
  const le = landed?.per_sku;
  const fe = fnc?.per_sku;
  return (
    <div style={{ display: "grid", gap: 20 }}>
      <div>
        <h3 style={{ fontSize: 14, margin: "0 0 8px" }}>Landed cost (fully loaded $/unit)</h3>
        {!Array.isArray(le) || !le.length ? (
          <p style={{ color: "#64748b", fontSize: 13 }}>No landed_cost_economics.per_sku.</p>
        ) : (
          <div style={{ overflow: "auto", border: "1px solid #e2e8f0", borderRadius: 8 }}>
            <table style={tableBase()}>
              <thead>
                <tr style={{ background: "#f1f5f9", textAlign: "left" }}>
                  <th style={{ padding: 8 }}>SKU</th>
                  <th style={{ padding: 8 }}>$/unit</th>
                  <th style={{ padding: 8 }}>Mock parcel</th>
                  <th style={{ padding: 8 }}>Transfer /unit</th>
                </tr>
              </thead>
              <tbody>
                {le.map((r) => {
                  const c = r.components_usd_per_unit || {};
                  return (
                    <tr key={r.sku} style={{ borderTop: "1px solid #e2e8f0" }}>
                      <td style={{ padding: 8, fontFamily: "monospace" }}>{r.sku}</td>
                      <td style={{ padding: 8 }}>{r.fully_loaded_usd_per_unit ?? "—"}</td>
                      <td style={{ padding: 8 }}>{c.mock_outbound_parcel_usd_per_unit ?? "—"}</td>
                      <td style={{ padding: 8 }}>{c.inter_warehouse_transfer_usd_per_unit_monthly_model ?? "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
      <div>
        <h3 style={{ fontSize: 14, margin: "0 0 8px" }}>Fulfillment network (allocated vs single-hub)</h3>
        {!Array.isArray(fe) || !fe.length ? (
          <p style={{ color: "#64748b", fontSize: 13 }}>No fulfillment comparison.</p>
        ) : (
          <div style={{ overflow: "auto", border: "1px solid #e2e8f0", borderRadius: 8 }}>
            <table style={tableBase()}>
              <thead>
                <tr style={{ background: "#f1f5f9", textAlign: "left" }}>
                  <th style={{ padding: 8 }}>SKU</th>
                  <th style={{ padding: 8 }}>Verdict</th>
                  <th style={{ padding: 8 }}>Summary</th>
                </tr>
              </thead>
              <tbody>
                {fe.map((r) => {
                  const intel = r.intelligence || {};
                  return (
                    <tr key={r.sku} style={{ borderTop: "1px solid #e2e8f0", verticalAlign: "top" }}>
                      <td style={{ padding: 8, fontFamily: "monospace" }}>{r.sku}</td>
                      <td style={{ padding: 8 }}>{intel.verdict ?? "—"}</td>
                      <td style={{ padding: 8, fontSize: 12 }}>{intel.headline ?? "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function ProductResearchEconomicsPanel({ pre }) {
  if (!pre?.outputs) {
    return (
      <p style={{ color: "#64748b", fontSize: 13 }}>
        No <code>product_research_economics</code> on this run. Enable it under advanced options (matches API default{" "}
        <code>include_product_research_economics: true</code>).
      </p>
    );
  }
  const ours = pre.outputs.ours;
  const prRows = ours?.product_research_by_sku;
  return (
    <div>
      <p style={{ fontSize: 13, color: "#475569", marginTop: 0 }}>
        Mirrors backend slots <code>outputs.original</code> (inputs + demand + placement summary) and{" "}
        <code>outputs.ours</code> (economics + FBA/FBM prep + fee scenarios when SP-API/data allow).
      </p>
      {Array.isArray(prRows) && prRows.length > 0 && (
        <div style={{ overflow: "auto", border: "1px solid #e2e8f0", borderRadius: 8, marginTop: 12 }}>
          <table style={tableBase()}>
            <thead>
              <tr style={{ background: "#f1f5f9", textAlign: "left" }}>
                <th style={{ padding: 8 }}>SKU</th>
                <th style={{ padding: 8 }}>FBM breakdown / scenarios</th>
              </tr>
            </thead>
            <tbody>
              {prRows.slice(0, 30).map((r) => (
                <tr key={r.sku} style={{ borderTop: "1px solid #e2e8f0", verticalAlign: "top" }}>
                  <td style={{ padding: 8, fontFamily: "monospace" }}>{r.sku}</td>
                  <td style={{ padding: 8, fontSize: 11 }}>
                    <pre style={{ margin: 0, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                      {JSON.stringify(r.scenarios || r.fbm_fulfillment_services_breakdown || r, null, 2).slice(0, 1200)}
                      {(JSON.stringify(r).length > 1200 ? "\n…" : "")}
                    </pre>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <details style={{ marginTop: 12 }}>
        <summary style={{ cursor: "pointer", fontSize: 13 }}>Raw product_research_economics JSON</summary>
        <pre
          style={{
            background: "#0f172a",
            color: "#e2e8f0",
            padding: 12,
            fontSize: 10,
            overflow: "auto",
            maxHeight: 320,
            marginTop: 8,
            borderRadius: 6,
          }}
        >
          {JSON.stringify(pre, null, 2)}
        </pre>
      </details>
    </div>
  );
}

function RunResults({ data }) {
  if (!data) return null;
  const synth = data.item_intelligence_synthesis;
  const pmg = data.placement_mock_rate_grids;
  const means = pmg?.mean_mock_parcel_usd_by_warehouse;
  const sellerPmg = pmg?.seller_order_planning_source;
  const gaps = data.catalog_physical_gaps || [];
  const ux = data.ux;

  return (
    <>
      {ux?.requires_manual_package_input && (
        <section
          style={{
            marginTop: 20,
            padding: "14px 16px",
            borderRadius: 8,
            border: "2px solid #f97316",
            background: "#fff7ed",
          }}
        >
          <h2 style={{ margin: "0 0 8px", fontSize: 16, color: "#9a3412" }}>Manual package input needed</h2>
          <p style={{ margin: "0 0 10px", fontSize: 14, lineHeight: 1.55, color: "#431407" }}>{ux.prompt}</p>
          <p style={{ margin: "0 0 8px", fontSize: 13, color: "#7c2d12" }}>
            SP-API Catalog (env credentials) and Keepa did not supply usable weight + dimensions for:
          </p>
          <ul style={{ margin: 0, paddingLeft: 20, fontSize: 13 }}>
            {gaps.map((g) => (
              <li key={g.sku}>
                <code>{g.sku}</code> ({g.asin || "no ASIN"}) — missing: {Array.isArray(g.missing_fields) ? g.missing_fields.join(", ") : "—"}
              </li>
            ))}
          </ul>
          <p style={{ margin: "12px 0 0", fontSize: 13, color: "#431407" }}>
            Use <strong>Advanced → manual_package_by_sku JSON</strong> below, or{" "}
            <code>PUT …/catalog/items</code> with <code>weight_lb</code> and <code>length_in</code> / <code>width_in</code> /{" "}
            <code>height_in</code>, then run again.
          </p>
        </section>
      )}

      {data.data_store_routing && (
        <Section
          title="Where data is stored (DB routing)"
          subtitle="Use this when deciding what to refresh every 2–4 weeks vs live API calls."
        >
          <ul style={{ fontSize: 13, lineHeight: 1.6, paddingLeft: 20, color: "#334155" }}>
            <li>
              <strong>SKU catalog</strong> — {data.data_store_routing.sku_catalog}
            </li>
            <li>
              <strong>Listing / demand cache</strong> — {data.data_store_routing.listing_and_demand_cache}
            </li>
            <li>
              <strong>Transport observations</strong> — {data.data_store_routing.transport_observations}
            </li>
            <li style={{ marginTop: 8, fontSize: 12, color: "#64748b" }}>{data.data_store_routing.note}</li>
          </ul>
        </Section>
      )}

      {data.planning_context && (
        <Section
          title="Planning context (server)"
          subtitle="planning_context on the response — automatic ASIN package fills, overrides, and gap list mirrored from the run."
        >
          <PackageEnrichmentAutomaticTable rows={data.planning_context.package_enrichment_automatic} />
          {data.planning_context.planning_monthly_units_override_result &&
            Object.keys(data.planning_context.planning_monthly_units_override_result).length > 0 && (
              <details style={{ marginTop: 12, fontSize: 12 }}>
                <summary style={{ cursor: "pointer" }}>planning_monthly_units_override_result</summary>
                <pre
                  style={{
                    marginTop: 8,
                    background: "#f8fafc",
                    border: "1px solid #e2e8f0",
                    borderRadius: 8,
                    padding: 10,
                    fontSize: 11,
                    overflow: "auto",
                    maxHeight: 200,
                  }}
                >
                  {JSON.stringify(data.planning_context.planning_monthly_units_override_result, null, 2)}
                </pre>
              </details>
            )}
        </Section>
      )}

      <Section
        title="Inventory: how much to position and where"
        subtitle="From allocation.lines — recommended_monthly_units per warehouse_id (model uses monthly demand × target shares; integer split). Use with client ops, not as a WMS pick list."
      >
        <InventoryPlacementTable allocation={data.allocation} />
        <NetworkAdjustmentNotes allocation={data.allocation} />
      </Section>

      <Section
        title="Warehouse network scenarios (same run)"
        subtitle="From warehouse_network_recommendation_options — single-DC vs multi-DC plus transfer-MOQ stocking nudges. Shipped on every item-intelligence response alongside allocation and PRO; not gated on product_research_economics."
      >
        <WarehouseNetworkScenariosPanel
          wno={data.warehouse_network_recommendation_options}
          trim={data.client_warehouse_network_trim}
          recommendedNetwork={data.recommended_warehouse_network}
        />
      </Section>

      <Section
        title="Executive summary"
        subtitle="From item_intelligence_synthesis.run_summary_bullets (fulfillment + cost drivers)."
      >
        {Array.isArray(synth?.run_summary_bullets) && synth.run_summary_bullets.length > 0 ? (
          <ul style={{ margin: 0, paddingLeft: 20, lineHeight: 1.55, fontSize: 14 }}>
            {synth.run_summary_bullets.map((b, i) => (
              <li key={i} style={{ marginBottom: 6 }}>
                {b}
              </li>
            ))}
          </ul>
        ) : (
          <p style={{ color: "#64748b" }}>No run summary bullets.</p>
        )}
        {synth?.note && (
          <p style={{ fontSize: 12, color: "#64748b", marginTop: 12, fontStyle: "italic" }}>{synth.note}</p>
        )}
      </Section>

      <Section
        title="Per-SKU intelligence"
        subtitle="Synthesis merges fulfillment verdicts, placement notes, and negotiation levers per SKU."
      >
        <SynthesisPerSkuCards perSku={synth?.per_sku} />
      </Section>

      <Section
        title="Demand enrichment (marketplace + placement hints)"
        subtitle="demand_by_sku from Keepa/cache; monthly_units_est_mid is a whole number after volume_intelligence (rank↔review + optional calibration). Reviews (30d) and sales-rank change come from momentum_30d_ux. Per-DC cover uses warehouse_splits — allocator cover badge when inventory_placement_summary_v2 is present."
      >
        <DemandEnrichmentTable demandBySku={data.demand_by_sku} />
      </Section>

      <Section
        title="Mock placement context (parcel to hubs)"
        subtitle="From placement_mock_rate_grids — mean mock parcel USD by origin warehouse (backend-computed)."
      >
        <p style={{ margin: "0 0 8px", fontSize: 13 }}>
          Status: <code>{pmg?.status ?? "—"}</code> · <code>{String(data.placement_allocation_share_source ?? "—")}</code>
        </p>
        <RateShoppingExecutionSummary rss={pmg?.rate_shopping_execution_summary} lastMile={pmg?.last_mile_optimization_context} />
        {pmg?.warehouse_input_dedupe?.applied && (
          <p style={{ margin: "0 0 10px", fontSize: 12, color: "#92400e" }}>
            Warehouse list deduped to one node per contiguous-US state (see{" "}
            <code>placement_mock_rate_grids.warehouse_input_dedupe</code>).
          </p>
        )}
        {sellerPmg && (
          <div
            style={{
              marginBottom: 12,
              fontSize: 13,
              padding: "10px 12px",
              borderRadius: 8,
              border: "1px solid #a5b4fc",
              background: "#eef2ff",
            }}
          >
            <strong>Seller order-planning placement source</strong> (when present on planning-run responses):{" "}
            <code style={{ fontSize: 12 }}>{sellerPmg.rate_shop_warehouse_node_count ?? "—"}</code> rate-shop nodes · cap{" "}
            <code>{sellerPmg.rate_shop_max_warehouses_cap ?? "—"}</code>
            {sellerPmg.state_demand_weighting && (
              <span style={{ color: "#4338ca" }}>
                {" "}
                · <code>{sellerPmg.state_demand_weighting}</code>
              </span>
            )}
            {sellerPmg.note && <p style={{ margin: "8px 0 0", fontSize: 12, lineHeight: 1.5, color: "#3730a3" }}>{sellerPmg.note}</p>}
          </div>
        )}
        <h3 style={{ fontSize: 13, margin: "16px 0 8px", fontWeight: 600 }}>Per-warehouse routing (demand-weighted primary)</h3>
        <p style={{ margin: "0 0 8px", fontSize: 12, color: "#64748b", lineHeight: 1.5 }}>
          Which DC is primary for which states under the grid’s assignment, and demand-weighted mean mock parcel among states
          where that DC wins.
        </p>
        <WarehousesRoutingSummaryTable summary={pmg?.warehouses_routing_summary} />

        {means && typeof means === "object" ? (
          <>
            <h3 style={{ fontSize: 13, margin: "16px 0 8px", fontWeight: 600 }}>Mean mock parcel $ by origin warehouse</h3>
            <table style={tableBase()}>
              <tbody>
                {Object.entries(means).map(([wid, v]) => (
                  <tr key={wid} style={{ borderTop: "1px solid #e2e8f0" }}>
                    <td style={{ padding: 8, fontFamily: "monospace" }}>{wid}</td>
                    <td style={{ padding: 8 }}>{typeof v === "number" ? v.toFixed(4) : String(v)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        ) : (
          <p style={{ color: "#64748b", fontSize: 13 }}>No mean mock parcel map.</p>
        )}

        <MockParcelMatrixSample matrix={pmg?.mock_parcel_usd_by_warehouse_by_state} />
      </Section>

      <Section
        title="Multi-DC placement / NVIDIA cuOpt (tri-modal)"
        subtitle="multi_dc_placement_tri_modal — fusion of allocation + mock grids + optional matrix extensions; baseline vs NVIDIA solve. Omitted when disabled in request or settings, or when the solver graph has insufficient DCs."
      >
        <CuOptTriModalPanel
          triModal={data.multi_dc_placement_tri_modal}
          rateShoppingRss={pmg?.rate_shopping_execution_summary}
          rateShoppingLastMile={pmg?.last_mile_optimization_context}
        />
      </Section>

      <Section title="Economics & fulfillment comparison" subtitle="landed_cost_economics + fulfillment_network_comparison.">
        <LandedAndFulfillmentTables landed={data.landed_cost_economics} fnc={data.fulfillment_network_comparison} />
      </Section>

      <Section
        title="Product research economics (PRO bundle)"
        subtitle="Same contract as API: four output surfaces; default run requests original + ours via server defaults."
      >
        <ProductResearchEconomicsPanel pre={data.product_research_economics} />
      </Section>

      {data.meta?.pipeline_stages && (
        <Section title="Pipeline" subtitle="meta.pipeline_stages from attach_four_views_and_pipeline.">
          <ul style={{ fontSize: 13, paddingLeft: 20 }}>
            {data.meta.pipeline_stages.map((s, i) => (
              <li key={i}>
                {s.name}: {s.status}
                {s.note ? ` — ${s.note}` : ""}
              </li>
            ))}
          </ul>
        </Section>
      )}

      <details style={{ marginTop: 24 }}>
        <summary style={{ cursor: "pointer" }}>Full response JSON</summary>
        <pre
          style={{
            background: "#0f172a",
            color: "#e2e8f0",
            padding: 16,
            fontSize: 10,
            overflow: "auto",
            maxHeight: 480,
            marginTop: 8,
          }}
        >
          {JSON.stringify(data, null, 2)}
        </pre>
      </details>
    </>
  );
}

export default function ProductResearchPage() {
  const [items, setItems] = useState(null);
  const [runResult, setRunResult] = useState(null);
  const [msg, setMsg] = useState("");
  const [postal, setPostal] = useState("07208");

  const [refreshKeepa, setRefreshKeepa] = useState(false);
  const [preserveShares, setPreserveShares] = useState(true);
  const [autoExpand, setAutoExpand] = useState(false);
  const [includeProEcon, setIncludeProEcon] = useState(true);
  const [spApiFees, setSpApiFees] = useState(true);
  const [hubId, setHubId] = useState("");
  const [skuFilter, setSkuFilter] = useState("");
  const [upcResolve, setUpcResolve] = useState("");
  const [outOriginal, setOutOriginal] = useState(true);
  const [outOurs, setOutOurs] = useState(true);
  const [outPlus, setOutPlus] = useState(false);
  const [outNvidia, setOutNvidia] = useState(false);
  const [omitCuoptTriModal, setOmitCuoptTriModal] = useState(false);
  const [omitNvidiaCuoptLayer, setOmitNvidiaCuoptLayer] = useState(false);
  const [cuoptEnrichmentJson, setCuoptEnrichmentJson] = useState("");
  const [manualPackageBySkuJson, setManualPackageBySkuJson] = useState("");

  const configured = Boolean(tenant && warehouse);

  function buildRunBody() {
    const zip = postal.replace(/\s/g, "").slice(0, 5);
    const body = {
      warehouses: [{ id: `${warehouse}_origin`, postal: zip || "10001" }],
      lanes: [],
    };

    if (refreshKeepa) body.refresh_keepa = true;
    if (!preserveShares) body.preserve_warehouse_target_shares = false;
    if (autoExpand) body.auto_expand_warehouse_network = true;
    if (!includeProEcon) body.include_product_research_economics = false;
    if (omitCuoptTriModal) body.include_cuopt_tri_modal = false;
    if (omitNvidiaCuoptLayer) body.include_nvidia_cuopt_layer = false;
    const ceRaw = cuoptEnrichmentJson.trim();
    if (ceRaw) {
      try {
        body.cuopt_enrichment = JSON.parse(ceRaw);
      } catch {
        /* invalid JSON ignored here; runItemIntelligence validates */
      }
    }
    if (hubId.trim()) body.hub_warehouse_id = hubId.trim();
    const skus = skuFilter
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    if (skus.length) body.sku_filter = skus;
    if (upcResolve.trim()) body.product_research_resolve_upc = upcResolve.trim();
    body.product_research_include_sp_api_fees = spApiFees;

    if (includeProEcon) {
      const outs = [];
      if (outOriginal) outs.push("original");
      if (outOurs) outs.push("ours");
      if (outPlus) outs.push("ours_plus_nvidia_enhancements");
      if (outNvidia) outs.push("nvidia_only");
      if (outs.length) body.product_research_outputs = outs;
    }

    const mpRaw = manualPackageBySkuJson.trim();
    if (mpRaw) {
      try {
        body.manual_package_by_sku = JSON.parse(mpRaw);
      } catch {
        /* validated in runItemIntelligence */
      }
    }

    return body;
  }

  async function loadCatalog() {
    setMsg("");
    setRunResult(null);
    try {
      const r = await api(`/v1/operational/${tenant}/catalog/items?limit=100`);
      setItems(r.items || []);
      setMsg(`Loaded ${(r.items || []).length} catalog rows.`);
    } catch (e) {
      setMsg(String(e.message));
      setItems(null);
    }
  }

  async function runItemIntelligence() {
    setMsg("");
    setRunResult(null);
    try {
      const ceRaw = cuoptEnrichmentJson.trim();
      if (ceRaw) {
        JSON.parse(ceRaw);
      }
      const mpRaw = manualPackageBySkuJson.trim();
      if (mpRaw) {
        JSON.parse(mpRaw);
      }
      const body = buildRunBody();
      if (mpRaw && body.manual_package_by_sku === undefined) {
        setMsg("manual_package_by_sku JSON is invalid — fix or clear the field.");
        return;
      }
      const r = await api(`/v1/operational/${tenant}/${warehouse}/item-intelligence/run`, {
        method: "POST",
        body: JSON.stringify(body),
      });
      setRunResult(r);
      setMsg("Run complete — intelligence below matches this request and backend defaults where omitted.");
    } catch (e) {
      if (e instanceof SyntaxError && cuoptEnrichmentJson.trim()) {
        setMsg(`cuOpt enrichment JSON: ${e.message}`);
        return;
      }
      if (e instanceof SyntaxError && manualPackageBySkuJson.trim()) {
        setMsg(`manual_package_by_sku JSON: ${e.message}`);
        return;
      }
      setMsg(String(e.message));
    }
  }

  return (
    <div style={{ maxWidth: 1000, margin: "0 auto", padding: 24 }}>
      <h1 style={{ marginTop: 0 }}>Product research</h1>
      <p style={{ fontSize: 12, color: "#64748b", marginTop: -6, marginBottom: 12 }}>
        New panels (mock rate shopping counts, allocator-weighted cover in the demand table, cuOpt cross-links) load from
        this bundle — if you do not see them after a pull, rebuild <code>portal/dist</code>{" "}
        (<code>cd portal &amp;&amp; npm run build</code>) or run <code>npm run dev</code>.
      </p>
      <p style={{ color: "#475569", lineHeight: 1.55, fontSize: 14 }}>
        Runs <code>POST …/item-intelligence/run</code> with options aligned to{" "}
        <code>ItemIntelligenceRunBody</code>. The UI surfaces the same artifacts the backend already returns: allocation
        (inventory by DC), <strong>warehouse network scenarios</strong> (single vs multi-DC + MOQ nudges, same response),
        demand enrichment, synthesis, economics, fulfillment comparison, and optional PRO economics. After you run, scroll to{" "}
        <strong>Mock placement context</strong> for rate-shop execution summary and to <strong>Demand enrichment</strong> for
        per-DC cover (allocator badge when the API returns <code>inventory_placement_summary_v2</code>).
      </p>

      {!configured && (
        <p style={{ background: "#fef3c7", padding: 12, borderRadius: 8 }}>
          Set <code>VITE_DEMO_TENANT</code> and <code>VITE_DEMO_WAREHOUSE</code> in <code>portal/.env.local</code> if needed.
        </p>
      )}

      <p style={{ fontSize: 14 }}>
        <strong>Scope:</strong> tenant <code>{tenant}</code>, operational warehouse <code>{warehouse}</code>
      </p>

      <div style={{ marginBottom: 16 }}>
        <button type="button" onClick={loadCatalog}>
          Load catalog
        </button>
      </div>

      {items && items.length > 0 && (
        <div style={{ overflow: "auto", marginBottom: 20, border: "1px solid #e2e8f0", borderRadius: 8 }}>
          <table style={tableBase()}>
            <thead>
              <tr style={{ background: "#f8fafc", textAlign: "left" }}>
                <th style={{ padding: 8 }}>SKU</th>
                <th style={{ padding: 8 }}>ASIN</th>
                <th style={{ padding: 8 }}>weight_lb</th>
                <th style={{ padding: 8 }}>L×W×H in</th>
              </tr>
            </thead>
            <tbody>
              {items.slice(0, 40).map((row) => (
                <tr key={row.sku} style={{ borderTop: "1px solid #f1f5f9" }}>
                  <td style={{ padding: 8, fontFamily: "monospace" }}>{row.sku}</td>
                  <td style={{ padding: 8 }}>{row.asin || "—"}</td>
                  <td style={{ padding: 8 }}>{row.weight_lb ?? "—"}</td>
                  <td style={{ padding: 8, fontSize: 12 }}>
                    {[row.length_in, row.width_in, row.height_in].every((x) => x != null && x !== "")
                      ? `${row.length_in}×${row.width_in}×${row.height_in}`
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h2 style={{ fontSize: 16 }}>Run</h2>
      <label style={{ display: "block", marginBottom: 12, fontSize: 14 }}>
        Origin postal (US ZIP) — drives mock placement grids
        <input value={postal} onChange={(e) => setPostal(e.target.value)} style={{ marginLeft: 8, padding: 6, width: 120 }} />
      </label>

      <details style={{ marginBottom: 16, border: "1px solid #e2e8f0", borderRadius: 8, padding: "10px 14px" }}>
        <summary style={{ cursor: "pointer", fontWeight: 600 }}>Advanced — match backend run body</summary>
        <div style={{ marginTop: 12, display: "grid", gap: 10, fontSize: 13 }}>
          <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <input type="checkbox" checked={includeProEcon} onChange={(e) => setIncludeProEcon(e.target.checked)} />
            include_product_research_economics (API default true)
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <input type="checkbox" checked={refreshKeepa} onChange={(e) => setRefreshKeepa(e.target.checked)} />
            refresh_keepa
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <input type="checkbox" checked={preserveShares} onChange={(e) => setPreserveShares(e.target.checked)} />
            preserve_warehouse_target_shares (default true)
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <input type="checkbox" checked={autoExpand} onChange={(e) => setAutoExpand(e.target.checked)} />
            auto_expand_warehouse_network
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <input type="checkbox" checked={spApiFees} onChange={(e) => setSpApiFees(e.target.checked)} />
            product_research_include_sp_api_fees (default true)
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <input type="checkbox" checked={omitCuoptTriModal} onChange={(e) => setOmitCuoptTriModal(e.target.checked)} />
            include_cuopt_tri_modal: false (omit tri-modal block; default follows server settings)
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <input type="checkbox" checked={omitNvidiaCuoptLayer} onChange={(e) => setOmitNvidiaCuoptLayer(e.target.checked)} />
            include_nvidia_cuopt_layer: false (baseline-only tri-modal)
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <span>cuopt_enrichment (optional JSON — parcel overrides, forbidden arcs, linehaul legs, demand band, parcel_sensitivity_pct)</span>
            <textarea
              value={cuoptEnrichmentJson}
              onChange={(e) => setCuoptEnrichmentJson(e.target.value)}
              rows={5}
              placeholder='e.g. { "parcel_sensitivity_pct": 10 }'
              style={{ width: "100%", fontFamily: "monospace", fontSize: 12, padding: 8 }}
            />
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <span>
              manual_package_by_sku (optional JSON — third fallback after SP-API + Keepa; positive weight_lb and all three
              dims in inches)
            </span>
            <textarea
              value={manualPackageBySkuJson}
              onChange={(e) => setManualPackageBySkuJson(e.target.value)}
              rows={4}
              placeholder='e.g. { "MY-SKU": { "weight_lb": 2.1, "length_in": 12, "width_in": 9, "height_in": 5 } }'
              style={{ width: "100%", fontFamily: "monospace", fontSize: 12, padding: 8 }}
            />
          </label>
          <div>
            <span style={{ display: "block", marginBottom: 6 }}>product_research_outputs (empty = server default original + ours)</span>
            <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <input type="checkbox" checked={outOriginal} onChange={(e) => setOutOriginal(e.target.checked)} />
              original
            </label>
            <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <input type="checkbox" checked={outOurs} onChange={(e) => setOutOurs(e.target.checked)} />
              ours
            </label>
            <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <input type="checkbox" checked={outPlus} onChange={(e) => setOutPlus(e.target.checked)} />
              ours_plus_nvidia_enhancements
            </label>
            <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <input type="checkbox" checked={outNvidia} onChange={(e) => setOutNvidia(e.target.checked)} />
              nvidia_only
            </label>
          </div>
          <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            hub_warehouse_id (optional)
            <input value={hubId} onChange={(e) => setHubId(e.target.value)} placeholder="e.g. w1_origin" style={{ padding: 6, maxWidth: 280 }} />
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            sku_filter (comma-separated)
            <input value={skuFilter} onChange={(e) => setSkuFilter(e.target.value)} placeholder="SKU1, SKU2" style={{ padding: 6 }} />
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            product_research_resolve_upc (optional, needs SP-API)
            <input value={upcResolve} onChange={(e) => setUpcResolve(e.target.value)} style={{ padding: 6 }} />
          </label>
        </div>
      </details>

      <button type="button" onClick={runItemIntelligence}>
        Run item intelligence
      </button>

      {msg && <p style={{ marginTop: 16 }}>{msg}</p>}

      {runResult && <RunResults data={runResult} />}

      <p style={{ marginTop: 32, fontSize: 14 }}>
        <Link to="/">Home</Link>
      </p>
    </div>
  );
}

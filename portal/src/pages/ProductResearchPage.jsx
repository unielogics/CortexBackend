import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";

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
            <th style={{ padding: 10 }}>Est. monthly inter-DC transfer $</th>
          </tr>
        </thead>
        <tbody>
          {lines.map((line) => (
            <tr key={line.sku} style={{ borderTop: "1px solid #e2e8f0", verticalAlign: "top" }}>
              <td style={{ padding: 10, fontFamily: "monospace" }}>{line.sku}</td>
              <td style={{ padding: 10 }}>{line.monthly_demand_units ?? "—"}</td>
              <td style={{ padding: 10, fontSize: 12, lineHeight: 1.45 }}>{formatPlacement(line.placement)}</td>
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
      </p>
    </div>
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
            <th style={{ padding: 10 }}>Est. monthly units (mid)</th>
            <th style={{ padding: 10 }}>Inventory / cover hints</th>
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, 60).map((r) => {
            const inv = r.inventory_placement_summary;
            let hint = "—";
            if (inv?.human_readable_one_liner) hint = inv.human_readable_one_liner;
            else if (Array.isArray(inv?.splits) && inv.splits.length) {
              hint = inv.splits
                .map((s) => `${s.warehouse_id}: ~${s.suggested_units_for_target_cover ?? "?"} u (${s.target_days_cover ?? "?"}d)`)
                .join(" · ");
            }
            return (
              <tr key={r.sku} style={{ borderTop: "1px solid #e2e8f0", verticalAlign: "top" }}>
                <td style={{ padding: 10, fontFamily: "monospace" }}>{r.sku}</td>
                <td style={{ padding: 10 }}>{r.asin || "—"}</td>
                <td style={{ padding: 10 }}>{r.monthly_units_est_mid ?? r.status ?? "—"}</td>
                <td style={{ padding: 10, fontSize: 12, lineHeight: 1.45 }}>{hint}</td>
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

  return (
    <>
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
        subtitle="demand_by_sku from Keepa/cache; inventory_placement_summary sizes cover targets when velocity is known."
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
        {means && typeof means === "object" ? (
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
        ) : (
          <p style={{ color: "#64748b", fontSize: 13 }}>No mean mock parcel map.</p>
        )}
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
      const body = buildRunBody();
      const r = await api(`/v1/operational/${tenant}/${warehouse}/item-intelligence/run`, {
        method: "POST",
        body: JSON.stringify(body),
      });
      setRunResult(r);
      setMsg("Run complete — intelligence below matches this request and backend defaults where omitted.");
    } catch (e) {
      setMsg(String(e.message));
    }
  }

  return (
    <div style={{ maxWidth: 1000, margin: "0 auto", padding: 24 }}>
      <h1 style={{ marginTop: 0 }}>Product research</h1>
      <p style={{ color: "#475569", lineHeight: 1.55, fontSize: 14 }}>
        Runs <code>POST …/item-intelligence/run</code> with options aligned to{" "}
        <code>ItemIntelligenceRunBody</code>. The UI surfaces the same artifacts the backend already returns: allocation
        (inventory by DC), <strong>warehouse network scenarios</strong> (single vs multi-DC + MOQ nudges, same response),
        demand enrichment, synthesis, economics, fulfillment comparison, and optional PRO economics.
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
              </tr>
            </thead>
            <tbody>
              {items.slice(0, 40).map((row) => (
                <tr key={row.sku} style={{ borderTop: "1px solid #f1f5f9" }}>
                  <td style={{ padding: 8, fontFamily: "monospace" }}>{row.sku}</td>
                  <td style={{ padding: 8 }}>{row.asin || "—"}</td>
                  <td style={{ padding: 8 }}>{row.weight_lb ?? "—"}</td>
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

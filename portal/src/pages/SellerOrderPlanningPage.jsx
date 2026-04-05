import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import CuOptTriModalPanel from "../components/CuOptTriModalPanel.jsx";
import RateShoppingExecutionSummary from "../components/RateShoppingExecutionSummary.jsx";

function tableBase() {
  return { width: "100%", borderCollapse: "collapse", fontSize: 13 };
}

export default function SellerOrderPlanningPage() {
  const { id: engagementId } = useParams();
  const [msg, setMsg] = useState("");
  const [data, setData] = useState(null);
  const [fbm, setFbm] = useState(true);
  const [fba, setFba] = useState(true);
  const [weightLb, setWeightLb] = useState("1.4");
  const [csvBaseline, setCsvBaseline] = useState("");
  const [omitCuoptTriModal, setOmitCuoptTriModal] = useState(false);
  const [omitNvidiaCuoptLayer, setOmitNvidiaCuoptLayer] = useState(false);
  const [cuoptEnrichmentJson, setCuoptEnrichmentJson] = useState("");

  async function runPlanning() {
    setMsg("");
    setData(null);
    const modes = [];
    if (fbm) modes.push("fbm");
    if (fba) modes.push("fba");
    if (!modes.length) {
      setMsg("Select at least one fulfillment mode.");
      return;
    }
    const ceRaw = cuoptEnrichmentJson.trim();
    if (ceRaw) {
      try {
        JSON.parse(ceRaw);
      } catch (e) {
        setMsg(`cuOpt enrichment JSON: ${e.message}`);
        return;
      }
    }
    const body = {
      fulfillment_modes: modes,
      weight_lb_per_unit: parseFloat(weightLb) || 1.4,
    };
    if (csvBaseline.trim()) body.csv_baseline_fulfillment = csvBaseline.trim();
    if (omitCuoptTriModal) body.include_cuopt_tri_modal = false;
    if (omitNvidiaCuoptLayer) body.include_nvidia_cuopt_layer = false;
    if (ceRaw) body.cuopt_enrichment = JSON.parse(ceRaw);

    try {
      const r = await api(`/v1/assessment/engagements/${engagementId}/order-financials/planning-run`, {
        method: "POST",
        body: JSON.stringify(body),
      });
      setData(r);
      setMsg("Planning run complete.");
    } catch (e) {
      setMsg(String(e.message));
    }
  }

  const pmg = data?.placement_mock_rate_grids;
  const sellerPmg = pmg?.seller_order_planning_source;
  const scenFbm = data?.scenario_integrated_fbm;
  const wn = scenFbm?.warehouse_network;
  const sel = Array.isArray(wn?.selected_warehouses) ? wn.selected_warehouses : [];

  return (
    <div style={{ fontFamily: "system-ui", maxWidth: 980, margin: "2rem auto", padding: 24 }}>
      <Link to={`/e/${engagementId}`}>← Engagement {engagementId}</Link>
      <h1 style={{ marginTop: 16 }}>Order-financial planning run</h1>
      <p style={{ fontSize: 12, color: "#64748b", marginBottom: 12 }}>
        After <code>git pull</code>, rebuild the portal if the API serves <code>portal/dist</code>:{" "}
        <code>cd portal &amp;&amp; npm run build</code>.
      </p>
      <p style={{ color: "#475569", lineHeight: 1.55, fontSize: 14 }}>
        Calls <code>POST /v1/assessment/engagements/{"{id}"}/order-financials/planning-run</code>. Response includes FBM/FBA
        integrated scenarios, <code>placement_mock_rate_grids</code> (national rate-shop node expansion for cuOpt),{" "}
        <code>multi_dc_placement_tri_modal</code>, and envelope <code>tri_modal.nvidia_enhanced</code> pointing at the same
        tri-modal block.
      </p>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 16, marginBottom: 16, alignItems: "center" }}>
        <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <input type="checkbox" checked={fbm} onChange={(e) => setFbm(e.target.checked)} />
          FBM scenario
        </label>
        <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <input type="checkbox" checked={fba} onChange={(e) => setFba(e.target.checked)} />
          FBA scenario
        </label>
        <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
          weight_lb_per_unit
          <input value={weightLb} onChange={(e) => setWeightLb(e.target.value)} style={{ width: 72, padding: 6 }} />
        </label>
        <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
          csv_baseline_fulfillment
          <input
            value={csvBaseline}
            onChange={(e) => setCsvBaseline(e.target.value)}
            placeholder="fba | fbw | fbm"
            style={{ width: 120, padding: 6 }}
          />
        </label>
      </div>

      <details style={{ marginBottom: 16, border: "1px solid #e2e8f0", borderRadius: 8, padding: "10px 14px" }}>
        <summary style={{ cursor: "pointer", fontWeight: 600 }}>cuOpt / tri-modal (same flags as Product Research)</summary>
        <div style={{ marginTop: 12, display: "grid", gap: 10, fontSize: 13 }}>
          <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <input type="checkbox" checked={omitCuoptTriModal} onChange={(e) => setOmitCuoptTriModal(e.target.checked)} />
            include_cuopt_tri_modal: false
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <input type="checkbox" checked={omitNvidiaCuoptLayer} onChange={(e) => setOmitNvidiaCuoptLayer(e.target.checked)} />
            include_nvidia_cuopt_layer: false
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <span>cuopt_enrichment (optional JSON)</span>
            <textarea
              value={cuoptEnrichmentJson}
              onChange={(e) => setCuoptEnrichmentJson(e.target.value)}
              rows={4}
              style={{ width: "100%", fontFamily: "monospace", fontSize: 12, padding: 8 }}
            />
          </label>
        </div>
      </details>

      <button type="button" onClick={runPlanning}>
        Run planning
      </button>
      {msg && <p style={{ marginTop: 12 }}>{msg}</p>}

      {data && (
        <div style={{ marginTop: 28, display: "grid", gap: 24 }}>
          <section>
            <h2 style={{ fontSize: 16, margin: "0 0 8px" }}>Snapshot</h2>
            <p style={{ fontSize: 13, color: "#475569", margin: 0 }}>
              Integrated rate shopping: <code>{String(data.integrated_rate_shopping_effective ?? "—")}</code> · rows:{" "}
              <code>{data.order_analysis_snapshot?.row_count ?? "—"}</code> · est. monthly demand (planning):{" "}
              <code>{data.order_analysis_snapshot?.estimated_monthly_demand_units ?? "—"}</code>
            </p>
          </section>

          <section>
            <h2 style={{ fontSize: 16, margin: "0 0 8px" }}>FBM linehaul network vs national rate-shop grid</h2>
            <p style={{ fontSize: 13, color: "#64748b", lineHeight: 1.5, margin: "0 0 10px" }}>
              Linehaul economics may use a single active node; <code>placement_mock_rate_grids</code> can still expand to
              multiple DCs for zone comparison and cuOpt (see seller_order_planning_source).
            </p>
            <p style={{ fontSize: 13, margin: "0 0 8px" }}>
              Scenario status: <code>{scenFbm?.status ?? "—"}</code>
            </p>
            {sel.length > 0 ? (
              <div style={{ overflow: "auto", border: "1px solid #e2e8f0", borderRadius: 8 }}>
                <table style={tableBase()}>
                  <thead>
                    <tr style={{ background: "#f1f5f9", textAlign: "left" }}>
                      <th style={{ padding: 8 }}>id</th>
                      <th style={{ padding: 8 }}>postal</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sel.map((w) => (
                      <tr key={w.id || w.postal} style={{ borderTop: "1px solid #e2e8f0" }}>
                        <td style={{ padding: 8, fontFamily: "monospace", fontSize: 12 }}>{w.id ?? "—"}</td>
                        <td style={{ padding: 8 }}>{w.postal ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p style={{ color: "#64748b", fontSize: 13 }}>No selected_warehouses on FBM scenario (incomplete or missing).</p>
            )}
          </section>

          <section>
            <h2 style={{ fontSize: 16, margin: "0 0 8px" }}>placement_mock_rate_grids</h2>
            <p style={{ fontSize: 13, margin: "0 0 8px" }}>
              Status: <code>{pmg?.status ?? "—"}</code>
            </p>
            <RateShoppingExecutionSummary rss={pmg?.rate_shopping_execution_summary} lastMile={pmg?.last_mile_optimization_context} />
            {sellerPmg && (
              <div
                style={{
                  fontSize: 13,
                  padding: "12px 14px",
                  borderRadius: 8,
                  border: "1px solid #a5b4fc",
                  background: "#eef2ff",
                  marginBottom: 12,
                }}
              >
                <strong>seller_order_planning_source</strong>
                <div style={{ marginTop: 6 }}>
                  Rate-shop nodes: <code>{sellerPmg.rate_shop_warehouse_node_count ?? "—"}</code> · cap{" "}
                  <code>{sellerPmg.rate_shop_max_warehouses_cap ?? "—"}</code>
                </div>
                {sellerPmg.state_demand_weighting && (
                  <div style={{ marginTop: 4 }}>
                    Weighting: <code>{sellerPmg.state_demand_weighting}</code>
                  </div>
                )}
                {sellerPmg.note && <p style={{ margin: "10px 0 0", fontSize: 12, lineHeight: 1.5, color: "#3730a3" }}>{sellerPmg.note}</p>}
              </div>
            )}
            {pmg?.mean_mock_parcel_usd_by_warehouse && typeof pmg.mean_mock_parcel_usd_by_warehouse === "object" && (
              <div style={{ overflow: "auto", border: "1px solid #e2e8f0", borderRadius: 8 }}>
                <table style={tableBase()}>
                  <tbody>
                    {Object.entries(pmg.mean_mock_parcel_usd_by_warehouse).map(([wid, v]) => (
                      <tr key={wid} style={{ borderTop: "1px solid #e2e8f0" }}>
                        <td style={{ padding: 8, fontFamily: "monospace" }}>{wid}</td>
                        <td style={{ padding: 8 }}>{typeof v === "number" ? v.toFixed(4) : String(v)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section>
            <h2 style={{ fontSize: 16, margin: "0 0 8px" }}>multi_dc_placement_tri_modal</h2>
            <CuOptTriModalPanel
              triModal={data.multi_dc_placement_tri_modal}
              rateShoppingRss={pmg?.rate_shopping_execution_summary}
              rateShoppingLastMile={pmg?.last_mile_optimization_context}
            />
          </section>

          <section>
            <h2 style={{ fontSize: 16, margin: "0 0 8px" }}>tri_modal envelope</h2>
            <p style={{ fontSize: 13, color: "#64748b", margin: "0 0 8px" }}>
              <code>nvidia_enhanced</code> duplicates <code>multi_dc_placement_tri_modal</code> for clients that read the
              tri-modal envelope only.
            </p>
            <details style={{ fontSize: 12 }}>
              <summary style={{ cursor: "pointer" }}>tri_modal (trimmed — baseline_unie is large)</summary>
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
                {JSON.stringify(
                  data.tri_modal
                    ? {
                        version: data.tri_modal.version,
                        original_input: data.tri_modal.original_input,
                        baseline_unie_keys:
                          data.tri_modal.baseline_unie && typeof data.tri_modal.baseline_unie === "object"
                            ? Object.keys(data.tri_modal.baseline_unie)
                            : [],
                        nvidia_enhanced_present: Boolean(data.tri_modal.nvidia_enhanced),
                      }
                    : null,
                  null,
                  2,
                )}
              </pre>
            </details>
          </section>

          <details style={{ fontSize: 12 }}>
            <summary style={{ cursor: "pointer" }}>Full response JSON</summary>
            <pre
              style={{
                background: "#0f172a",
                color: "#e2e8f0",
                padding: 12,
                fontSize: 9,
                overflow: "auto",
                maxHeight: 400,
                marginTop: 8,
                borderRadius: 6,
              }}
            >
              {JSON.stringify(data, null, 2)}
            </pre>
          </details>
        </div>
      )}

      <p style={{ marginTop: 24 }}>
        <Link to="/">Home</Link> · <Link to="/pro">Product research</Link>
      </p>
    </div>
  );
}

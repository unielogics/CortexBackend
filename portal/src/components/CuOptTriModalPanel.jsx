/**
 * Maps backend multi_dc_placement_tri_modal + related keys for UI.
 * Item intelligence (PRO) and seller order-financial planning-run share the same tri-modal shape;
 * seller runs may add seller_cuopt_context inside the block.
 */

import RateShoppingExecutionSummary from "./RateShoppingExecutionSummary.jsx";

const SOLVER_SOURCE_LABELS = {
  order_financial_planning_fbm: "Seller planning (FBM scenario)",
  order_financial_planning_fbm_selected_multi_dc: "Seller planning — multiple DCs in smart-network selection",
  order_financial_planning_fbm_national_rate_shop_pool:
    "Seller planning — national rate-shop pool (48-state hubs; may differ from single linehaul node)",
  order_financial_planning_fbm_insufficient_nodes: "Seller planning — not enough DCs for cuOpt graph",
  multi_dc_parallel_scenario: "Product research — parallel multi-DC intelligence block",
  warehouse_network_recommendation_multi_dc: "Product research — warehouse network option: multi-DC",
};

function labelSolverSource(raw) {
  if (!raw) return "—";
  return SOLVER_SOURCE_LABELS[raw] || String(raw);
}

function StatusPill({ ok, children }) {
  return (
    <span
      style={{
        fontSize: 12,
        padding: "3px 10px",
        borderRadius: 999,
        background: ok ? "#dcfce7" : "#f1f5f9",
        color: ok ? "#166534" : "#475569",
        fontWeight: 600,
      }}
    >
      {children}
    </span>
  );
}

export default function CuOptTriModalPanel({ triModal, rateShoppingRss, rateShoppingLastMile }) {
  if (!triModal || typeof triModal !== "object") {
    return (
      <div style={{ display: "grid", gap: 12 }}>
        {(rateShoppingRss || rateShoppingLastMile) && (
          <RateShoppingExecutionSummary rss={rateShoppingRss} lastMile={rateShoppingLastMile} />
        )}
        <p style={{ color: "#64748b", fontSize: 13 }}>
          No <code>multi_dc_placement_tri_modal</code> on this response (disabled, skipped, or insufficient DCs for the
          solver graph).
        </p>
      </div>
    );
  }

  const elig = triModal.eligibility || {};
  const nv = triModal.nvidia_enhanced;
  const base = triModal.baseline_without_nvidia;
  const compare = triModal.solver_inputs_original_vs_enhanced;
  const micro = triModal.microscopic_placement_expenses;
  const enrich = triModal.cuopt_enrichment_analysis;
  const audit = triModal.cuopt_fusion_audit;
  const sellerCtx = triModal.seller_cuopt_context;

  const nvOk = nv && String(nv.status) === "complete";
  const src =
    elig.cuopt_solver_network_source ||
    compare?.note?.slice(0, 80) ||
    (sellerCtx && sellerCtx.solver_network_source) ||
    null;

  return (
    <div style={{ display: "grid", gap: 14 }}>
      {(rateShoppingRss || rateShoppingLastMile) && (
        <div>
          <p style={{ margin: "0 0 6px", fontSize: 12, fontWeight: 600, color: "#475569" }}>
            Mock parcel rate shopping (same run as tri-modal inputs)
          </p>
          <RateShoppingExecutionSummary rss={rateShoppingRss} lastMile={rateShoppingLastMile} />
        </div>
      )}
      <p style={{ margin: 0, fontSize: 13, color: "#475569", lineHeight: 1.55 }}>
        <strong>Tri-modal</strong> compares pre-fusion vs post-fusion solver rows, runs an internal lane baseline without
        NVIDIA, then optionally calls cuOpt. <strong>Fusion</strong> uses allocation + mock parcel grids + economics when
        present; seller planning may use a <strong>national rate-shop pool</strong> so the graph can have multiple DCs even
        when linehaul keeps one active node.
      </p>

      {triModal.status === "skipped" && triModal.message && (
        <p style={{ margin: 0, fontSize: 13, color: "#92400e", background: "#fffbeb", padding: "10px 12px", borderRadius: 8 }}>
          {triModal.message}
        </p>
      )}

      {sellerCtx && (
        <div
          style={{
            fontSize: 13,
            padding: "12px 14px",
            borderRadius: 8,
            border: "1px solid #c7d2fe",
            background: "#eef2ff",
          }}
        >
          <strong>Seller planning cuOpt context</strong>
          <div style={{ marginTop: 6, color: "#3730a3" }}>
            Network basis: <code>{sellerCtx.solver_network_source || "—"}</code>
          </div>
          {sellerCtx.note && <p style={{ margin: "8px 0 0", fontSize: 12, lineHeight: 1.5 }}>{sellerCtx.note}</p>}
        </div>
      )}

      <div style={{ display: "flex", flexWrap: "wrap", gap: 10, alignItems: "center" }}>
        <span style={{ fontSize: 13 }}>Solver network source:</span>
        <code style={{ fontSize: 12 }}>{labelSolverSource(src)}</code>
        {elig.cuopt_enrichment_matrix_extensions && (
          <span style={{ fontSize: 12, color: "#0369a1" }}>
            Matrix extensions on request (forbidden / linehaul legs)
          </span>
        )}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 12 }}>
        <div style={{ border: "1px solid #e2e8f0", borderRadius: 8, padding: 12, background: "#fafafa" }}>
          <div style={{ fontSize: 12, color: "#64748b", marginBottom: 6 }}>Baseline (no NVIDIA)</div>
          <StatusPill ok={base && String(base.status) !== "error"}>{base?.status ?? "—"}</StatusPill>
          <div style={{ fontSize: 11, marginTop: 8, color: "#64748b" }}>{base?.source ?? ""}</div>
        </div>
        <div style={{ border: "1px solid #e2e8f0", borderRadius: 8, padding: 12, background: "#fafafa" }}>
          <div style={{ fontSize: 12, color: "#64748b", marginBottom: 6 }}>NVIDIA / cuOpt</div>
          <StatusPill ok={nvOk}>{nv?.status ?? "—"}</StatusPill>
          <div style={{ fontSize: 11, marginTop: 8, color: "#64748b" }}>
            {nv?.source ? `source: ${nv.source}` : ""}
            {nv?.solver_solution_cost != null ? ` · cost: ${nv.solver_solution_cost}` : ""}
          </div>
        </div>
      </div>

      {compare && (
        <details style={{ fontSize: 13 }}>
          <summary style={{ cursor: "pointer", fontWeight: 600 }}>Solver rows: original vs enhanced (fusion)</summary>
          <p style={{ fontSize: 12, color: "#64748b", margin: "8px 0" }}>{compare.note}</p>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginTop: 8 }}>
            <div>
              <div style={{ fontSize: 11, fontWeight: 600, marginBottom: 4 }}>Original</div>
              <pre
                style={{
                  margin: 0,
                  fontSize: 10,
                  background: "#0f172a",
                  color: "#e2e8f0",
                  padding: 10,
                  borderRadius: 6,
                  maxHeight: 200,
                  overflow: "auto",
                }}
              >
                {JSON.stringify(compare.original_solver_warehouse_rows ?? [], null, 2)}
              </pre>
            </div>
            <div>
              <div style={{ fontSize: 11, fontWeight: 600, marginBottom: 4 }}>Enhanced</div>
              <pre
                style={{
                  margin: 0,
                  fontSize: 10,
                  background: "#0f172a",
                  color: "#e2e8f0",
                  padding: 10,
                  borderRadius: 6,
                  maxHeight: 200,
                  overflow: "auto",
                }}
              >
                {JSON.stringify(compare.enhanced_solver_warehouse_rows ?? [], null, 2)}
              </pre>
            </div>
          </div>
        </details>
      )}

      {micro && (
        <details style={{ fontSize: 13 }}>
          <summary style={{ cursor: "pointer", fontWeight: 600 }}>Microscopic placement / fusion audit</summary>
          <p style={{ fontSize: 12, color: "#64748b", margin: "8px 0" }}>{micro.note}</p>
          {micro.fusion_audit && (
            <pre
              style={{
                marginTop: 8,
                fontSize: 10,
                background: "#f8fafc",
                border: "1px solid #e2e8f0",
                padding: 10,
                borderRadius: 6,
                maxHeight: 180,
                overflow: "auto",
              }}
            >
              {JSON.stringify(
                {
                  enrichment_row_counts: micro.fusion_audit.enrichment_row_counts,
                  parcel_override_request_meta: micro.fusion_audit.parcel_override_request_meta,
                  schema_version: micro.fusion_audit.schema_version,
                },
                null,
                2,
              )}
            </pre>
          )}
        </details>
      )}

      {enrich && (
        <details style={{ fontSize: 13 }}>
          <summary style={{ cursor: "pointer", fontWeight: 600 }}>cuOpt enrichment analysis (fingerprint, sensitivity)</summary>
          <p style={{ fontSize: 12, color: "#64748b", margin: "8px 0" }}>
            Fingerprint: <code>{enrich.cuopt_fusion_inputs_fingerprint_sha256 ?? "—"}</code>
          </p>
          {enrich.parcel_rate_sensitivity && (
            <p style={{ fontSize: 12, margin: "6px 0" }}>
              Parcel ±% stress (no extra NVIDIA call): <code>{enrich.parcel_rate_sensitivity.parcel_pct ?? "—"}</code>
            </p>
          )}
          {enrich.waterfall_bridge && enrich.waterfall_bridge.schema_version && (
            <pre style={{ fontSize: 10, background: "#f8fafc", padding: 8, borderRadius: 6, overflow: "auto" }}>
              {JSON.stringify(enrich.waterfall_bridge, null, 2)}
            </pre>
          )}
        </details>
      )}

      {audit && !micro?.fusion_audit && (
        <details style={{ fontSize: 13 }}>
          <summary style={{ cursor: "pointer" }}>cuopt_fusion_audit (raw)</summary>
          <pre style={{ fontSize: 10, maxHeight: 160, overflow: "auto", background: "#f1f5f9", padding: 8 }}>{JSON.stringify(audit, null, 2)}</pre>
        </details>
      )}

      <details style={{ fontSize: 12 }}>
        <summary style={{ cursor: "pointer" }}>Full multi_dc_placement_tri_modal JSON</summary>
        <pre
          style={{
            background: "#0f172a",
            color: "#e2e8f0",
            padding: 12,
            fontSize: 10,
            overflow: "auto",
            maxHeight: 360,
            marginTop: 8,
            borderRadius: 6,
          }}
        >
          {JSON.stringify(triModal, null, 2)}
        </pre>
      </details>
    </div>
  );
}

export { labelSolverSource, SOLVER_SOURCE_LABELS };

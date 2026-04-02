import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

export default function AuditSynthesisView({ synthesis, viz }) {
  if (!synthesis) return null;

  return (
    <>
      <h3>Synthesis &amp; suggestions</h3>
      <p style={{ color: "#555", fontSize: 14 }}>
        Plain-language summary is generated with your data (no LLM required). Technical JSON stays below for
        developers.
      </p>

      {synthesis.human_readable?.headline && (
        <div
          style={{
            background: "linear-gradient(135deg, #f0f7ff 0%, #f8fafc 100%)",
            border: "1px solid #cfe2ff",
            borderRadius: 10,
            padding: "16px 18px",
            marginBottom: 20,
          }}
        >
          <div style={{ fontSize: 12, color: "#64748b", textTransform: "uppercase", letterSpacing: "0.04em" }}>
            Summary
          </div>
          <p style={{ fontSize: 18, fontWeight: 600, margin: "8px 0 0", color: "#0f172a", lineHeight: 1.35 }}>
            {synthesis.human_readable.headline}
          </p>
        </div>
      )}

      {Array.isArray(synthesis.human_readable?.summary_lines) && synthesis.human_readable.summary_lines.length > 0 && (
        <div style={{ marginBottom: 20 }}>
          <h4 style={{ margin: "0 0 10px", fontSize: 15 }}>In plain words</h4>
          <ul style={{ margin: 0, paddingLeft: 20, color: "#334155", lineHeight: 1.55 }}>
            {synthesis.human_readable.summary_lines.map((line, i) => (
              <li key={i} style={{ marginBottom: 8 }}>
                {line}
              </li>
            ))}
          </ul>
        </div>
      )}

      {Array.isArray(synthesis.human_readable?.at_a_glance) && synthesis.human_readable.at_a_glance.length > 0 && (
        <div style={{ marginBottom: 20 }}>
          <h4 style={{ margin: "0 0 10px", fontSize: 15 }}>At a glance</h4>
          <div style={{ display: "grid", gap: 10 }}>
            {synthesis.human_readable.at_a_glance.map((card, i) => (
              <div
                key={i}
                style={{
                  border: "1px solid #e2e8f0",
                  borderRadius: 8,
                  padding: "12px 14px",
                  background: "#fff",
                }}
              >
                <div style={{ fontWeight: 600, color: "#0f172a", marginBottom: 6 }}>{card.title}</div>
                <div style={{ fontSize: 14, color: "#475569", lineHeight: 1.5 }}>{card.body}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {(synthesis.human_readable?.benchmark_tier_plain ||
        synthesis.human_readable?.label_spend_plain ||
        synthesis.human_readable?.warehouse_economics_plain) && (
        <div style={{ marginBottom: 20 }}>
          <h4 style={{ margin: "0 0 10px", fontSize: 15 }}>Money and warehouse read</h4>
          <div style={{ fontSize: 14, color: "#334155", lineHeight: 1.6 }}>
            {synthesis.human_readable.benchmark_tier_plain && (
              <p style={{ margin: "0 0 10px" }}>{synthesis.human_readable.benchmark_tier_plain}</p>
            )}
            {synthesis.human_readable.label_spend_plain && (
              <p style={{ margin: "0 0 10px" }}>{synthesis.human_readable.label_spend_plain}</p>
            )}
            {synthesis.human_readable.warehouse_economics_plain && (
              <p style={{ margin: 0 }}>{synthesis.human_readable.warehouse_economics_plain}</p>
            )}
          </div>
        </div>
      )}

      {synthesis.human_readable?.what_this_means && (
        <p style={{ fontSize: 13, color: "#64748b", fontStyle: "italic", marginBottom: 20, lineHeight: 1.5 }}>
          {synthesis.human_readable.what_this_means}
        </p>
      )}

      {Array.isArray(synthesis.human_readable?.findings_for_humans) &&
        synthesis.human_readable.findings_for_humans.length > 0 && (
          <div style={{ marginBottom: 20 }}>
            <h4 style={{ margin: "0 0 10px", fontSize: 15 }}>What we noticed</h4>
            <ul style={{ margin: 0, paddingLeft: 20 }}>
              {synthesis.human_readable.findings_for_humans.map((f, i) => (
                <li key={i} style={{ marginBottom: 10, color: "#334155" }}>
                  <strong>{f.title}</strong>
                  <div style={{ marginTop: 4 }}>{f.detail}</div>
                </li>
              ))}
            </ul>
          </div>
        )}

      {Array.isArray(synthesis.human_readable?.next_steps) && synthesis.human_readable.next_steps.length > 0 && (
        <div style={{ marginBottom: 20 }}>
          <h4 style={{ margin: "0 0 10px", fontSize: 15 }}>Suggested next steps</h4>
          <ul style={{ margin: 0, paddingLeft: 20, color: "#334155", lineHeight: 1.55 }}>
            {synthesis.human_readable.next_steps.map((s, i) => (
              <li key={i} style={{ marginBottom: 6 }}>
                {s}
              </li>
            ))}
          </ul>
        </div>
      )}

      {Array.isArray(synthesis.human_readable?.warehouse_strategy_suggestions) &&
        synthesis.human_readable.warehouse_strategy_suggestions.length > 0 && (
          <div style={{ marginBottom: 24 }}>
            <h4 style={{ margin: "0 0 10px", fontSize: 15 }}>Warehouse &amp; network strategy</h4>
            <p style={{ color: "#64748b", fontSize: 13, marginTop: 0 }}>
              FBA prep vs FBM, billing mix, rate shopping, and single vs multi-DC — same family of ideas as catalog /
              multi-DC runs, grounded in your order and facility data.
            </p>
            <ul style={{ margin: 0, paddingLeft: 20, listStyle: "none" }}>
              {synthesis.human_readable.warehouse_strategy_suggestions.map((s, i) => (
                <li
                  key={i}
                  style={{
                    marginBottom: 14,
                    paddingLeft: 12,
                    borderLeft: "3px solid #cbd5e1",
                    color: "#334155",
                  }}
                >
                  <div style={{ fontSize: 12, color: "#64748b" }}>
                    {s.priority ? `${s.priority} · ` : ""}
                    {s.category || "strategy"}
                  </div>
                  <div style={{ fontWeight: 600, marginTop: 4 }}>{s.title}</div>
                  {s.detail ? <div style={{ marginTop: 6, lineHeight: 1.5 }}>{s.detail}</div> : null}
                  {Array.isArray(s.actions) && s.actions.length > 0 ? (
                    <ul style={{ margin: "8px 0 0", paddingLeft: 18, fontSize: 13 }}>
                      {s.actions.map((a, j) => (
                        <li key={j}>{a}</li>
                      ))}
                    </ul>
                  ) : null}
                </li>
              ))}
            </ul>
          </div>
        )}

      {(() => {
        const uploadList =
          synthesis.human_readable?.upload_opportunities_display ||
          synthesis.data_quality?.upload_opportunities ||
          [];
        if (!Array.isArray(uploadList) || uploadList.length === 0) return null;
        return (
          <div style={{ marginTop: 8 }}>
            <h4 style={{ margin: "0 0 8px" }}>Sharpen the analysis</h4>
            <p style={{ color: "#555", fontSize: 13, marginTop: 0 }}>
              Each item ties a data gap to what becomes clearer once you add or fix the feed.
            </p>
            <ul style={{ margin: 0, paddingLeft: 20 }}>
              {uploadList.map((u, i) => (
                <li key={i} style={{ marginBottom: 12 }}>
                  <span
                    style={{
                      fontSize: 11,
                      fontWeight: 600,
                      color:
                        u.priority === "high" ? "#b45309" : u.priority === "medium" ? "#1d4ed8" : "#6b7280",
                    }}
                  >
                    {u.priority_label || u.priority || "note"}
                  </span>
                  {u.category ? (
                    <span style={{ fontSize: 11, color: "#888", marginLeft: 8 }}>{u.category}</span>
                  ) : null}
                  <div style={{ fontWeight: 600, marginTop: 4 }}>{u.title}</div>
                  {u.detail ? <div style={{ color: "#444", fontSize: 14, marginTop: 4 }}>{u.detail}</div> : null}
                  {u.unlocks_plain ? (
                    <div style={{ fontSize: 13, color: "#374151", marginTop: 6 }}>{u.unlocks_plain}</div>
                  ) : Array.isArray(u.unlocks) && u.unlocks.length > 0 ? (
                    <div style={{ fontSize: 13, color: "#374151", marginTop: 6 }}>
                      <strong>Then you can see:</strong> {u.unlocks.join(" · ")}
                    </div>
                  ) : null}
                </li>
              ))}
            </ul>
          </div>
        );
      })()}

      {synthesis.ai_recommendations &&
        (synthesis.ai_recommendations.nim_invocation ||
          (Array.isArray(synthesis.ai_recommendations.items) && synthesis.ai_recommendations.items.length > 0) ||
          synthesis.ai_recommendations.source) && (
          <div
            style={{
              marginTop: 24,
              padding: "14px 16px",
              borderRadius: 8,
              border: "1px solid #a7f3d0",
              background: "#ecfdf5",
            }}
          >
            <h4 style={{ margin: "0 0 8px", fontSize: 15 }}>NVIDIA NIM (optional)</h4>
            {synthesis.ai_recommendations.nim_invocation && (
              <pre
                style={{
                  fontSize: 12,
                  margin: "0 0 12px",
                  padding: 10,
                  background: "#fff",
                  borderRadius: 6,
                  overflow: "auto",
                }}
              >
                {JSON.stringify(synthesis.ai_recommendations.nim_invocation, null, 2)}
              </pre>
            )}
            <p style={{ margin: "0 0 8px", fontSize: 13, color: "#065f46" }}>
              <code>source</code>: {synthesis.ai_recommendations.source || "—"} · items:{" "}
              {Array.isArray(synthesis.ai_recommendations.items) ? synthesis.ai_recommendations.items.length : 0}
            </p>
            {Array.isArray(synthesis.ai_recommendations.items) && synthesis.ai_recommendations.items.length > 0 && (
              <ul style={{ margin: 0, paddingLeft: 18, color: "#064e3b", lineHeight: 1.55 }}>
                {synthesis.ai_recommendations.items.map((it, i) => (
                  <li key={i} style={{ marginBottom: 12 }}>
                    <strong>{it.title}</strong>
                    {it.impact_axis ? (
                      <span style={{ fontSize: 12, color: "#047857", marginLeft: 8 }}>({it.impact_axis})</span>
                    ) : null}
                    {it.rationale ? <div style={{ marginTop: 6 }}>{it.rationale}</div> : null}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

      {(() => {
        const wi = synthesis.current_state?.warehouse_intelligence;
        const nop = wi?.network_opportunities;
        const nou = nop?.network_opportunity_units;
        const sug = nop?.suggestion_state_opportunities_30d;
        if (!nou && !sug?.total_monthly_units_active_window) return null;
        return (
          <div
            style={{
              marginTop: 20,
              padding: "14px 16px",
              borderRadius: 8,
              border: "1px solid #bfdbfe",
              background: "#eff6ff",
            }}
          >
            <h4 style={{ margin: "0 0 8px", fontSize: 15 }}>Network opportunities (Warehouse Audit System)</h4>
            {nou && (
              <p style={{ margin: "0 0 8px", fontSize: 14, color: "#1e3a5f" }}>
                NOU index — cumulative: <strong>{nou.cumulative_all_runs}</strong>, this run:{" "}
                <strong>{nou.this_computation_total}</strong>
              </p>
            )}
            {sug && Number(sug.total_monthly_units_active_window) > 0 && (
              <p style={{ margin: 0, fontSize: 13, color: "#334155" }}>
                State opportunities ({sug.window_days || 30}-day rolling): ~{sug.total_monthly_units_active_window}{" "}
                monthly units, ~${sug.total_monthly_revenue_potential_usd_active_window} revenue proxy (see API
                methodology).
              </p>
            )}
          </div>
        );
      })()}

      {Array.isArray(synthesis.themes) && synthesis.themes.length > 0 && (
        <div style={{ marginTop: 20 }}>
          <h4 style={{ margin: "0 0 8px", fontSize: 15 }}>Technical themes (for analysts)</h4>
          <ul style={{ margin: 0, paddingLeft: 20, fontSize: 14, color: "#475569" }}>
            {synthesis.themes.map((t, i) => (
              <li key={i} style={{ marginBottom: 6 }}>
                {t}
              </li>
            ))}
          </ul>
        </div>
      )}

      {synthesis.current_state?.warehouse_intelligence && (
        <details style={{ marginTop: 16 }}>
          <summary style={{ cursor: "pointer", color: "#64748b" }}>Raw warehouse metrics (JSON)</summary>
          <pre
            style={{
              background: "#0d1117",
              color: "#c9d1d9",
              padding: 12,
              fontSize: 12,
              overflow: "auto",
              marginTop: 8,
            }}
          >
            {JSON.stringify(
              {
                fulfillment_estimate: synthesis.current_state.warehouse_intelligence.fulfillment_estimate,
                estimated_cost_per_fulfillment_usd:
                  synthesis.current_state.warehouse_intelligence.estimated_cost_per_fulfillment_usd,
                billing_usd_total: synthesis.current_state.warehouse_intelligence.billing_usd_total,
                label_network_insights: synthesis.current_state.warehouse_intelligence.label_network_insights,
                capacity_baseline: synthesis.current_state.warehouse_intelligence.capacity_baseline,
                synthetic_fill: synthesis.current_state.warehouse_intelligence.synthetic_fill,
              },
              null,
              2
            )}
          </pre>
        </details>
      )}
      <details style={{ marginTop: 12 }}>
        <summary style={{ cursor: "pointer" }}>Full audit outcome JSON</summary>
        <pre style={{ background: "#111", color: "#ddd", padding: 16, overflow: "auto", marginTop: 8 }}>
          {JSON.stringify(synthesis, null, 2)}
        </pre>
      </details>

      {viz && viz.chart_cost_by_carrier?.length > 0 && (
        <div style={{ height: 280, marginTop: 24 }}>
          <h4>Spend by carrier</h4>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={viz.chart_cost_by_carrier}>
              <XAxis dataKey="carrier" />
              <YAxis />
              <Tooltip />
              <Bar dataKey="usd" fill="#3b82f6" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </>
  );
}

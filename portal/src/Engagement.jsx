import { useState } from "react";
import { useParams, Link } from "react-router-dom";
import { api } from "./api";
import AuditSynthesisView from "./components/AuditSynthesisView.jsx";

export default function Engagement() {
  const { id } = useParams();
  const [mappingJson, setMappingJson] = useState(
    JSON.stringify(
      {
        labels: {
          Tracking: "tracking_number",
          Amount: "label_amount_usd",
          Weight: "weight_lb",
          DestZip: "dest_postal",
          Carrier: "carrier",
        },
      },
      null,
      2,
    ),
  );
  const [runId, setRunId] = useState("");
  const [report, setReport] = useState(null);
  const [synthesis, setSynthesis] = useState(null);
  const [viz, setViz] = useState(null);
  const [msg, setMsg] = useState("");
  const [withNvidiaNimAi, setWithNvidiaNimAi] = useState(false);

  async function saveMapping() {
    setMsg("");
    try {
      const m = JSON.parse(mappingJson);
      await api(`/v1/assessment/engagements/${id}/column-mapping`, {
        method: "PUT",
        body: JSON.stringify({ mappings: m }),
      });
      setMsg("Mapping saved.");
    } catch (e) {
      setMsg(String(e.message));
    }
  }

  async function runAudit() {
    setMsg("");
    try {
      const narr = withNvidiaNimAi ? "true" : "false";
      const j = await api(`/v1/assessment/engagements/${id}/runs?with_narrative=${narr}`, { method: "POST" });
      setRunId(j.run_id);
      const rep = await api(`/v1/assessment/engagements/${id}/runs/${j.run_id}/report`);
      setReport(rep);
      const v = await api(`/v1/assessment/engagements/${id}/runs/${j.run_id}/visualization-data`);
      setViz(v);
      const syn = await api(`/v1/assessment/engagements/${id}/audit-synthesis`, {
        method: "POST",
        body: JSON.stringify({
          run_id: j.run_id,
          with_ai_recommendations: withNvidiaNimAi,
          ai_detail: "brief",
        }),
      });
      setSynthesis(syn);
      setMsg("Audit complete.");
    } catch (e) {
      setMsg(String(e.message));
    }
  }

  return (
    <div style={{ fontFamily: "system-ui", maxWidth: 900, margin: "2rem auto", padding: 24 }}>
      <Link to="/">← Home</Link>
      <h2>Engagement {id}</h2>
      <p style={{ fontSize: 14 }}>
        <Link to={`/e/${id}/planning`}>Order-financial planning run</Link> (cuOpt tri-modal + national rate-shop grids)
      </p>

      <h3>1. Column mapping (JSON)</h3>
      <textarea
        rows={12}
        style={{ width: "100%", fontFamily: "monospace", fontSize: 12 }}
        value={mappingJson}
        onChange={(e) => setMappingJson(e.target.value)}
      />
      <button type="button" onClick={saveMapping}>
        Save mapping
      </button>

      <h3>2. Upload CSV</h3>
      <p>Use multipart from API docs, or paste sample via curl. Required mapped: label_amount_usd, weight_lb, dest_postal.</p>

      <h3>3. Run audit</h3>
      <label style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12, cursor: "pointer" }}>
        <input
          type="checkbox"
          checked={withNvidiaNimAi}
          onChange={(e) => setWithNvidiaNimAi(e.target.checked)}
        />
        <span style={{ fontSize: 14 }}>
          NVIDIA NIM: <code>with_narrative</code> on run + <code>with_ai_recommendations</code> on audit-synthesis
        </span>
      </label>
      <button type="button" onClick={runAudit}>
        Run spine
      </button>
      {msg && <p>{msg}</p>}

      {report && (
        <>
          <h3>Report (spine)</h3>
          {Array.isArray(report.findings) && report.findings.length > 0 && (
            <ul>
              {report.findings.map((f, i) => (
                <li key={i}>
                  <strong>{f.type || "finding"}</strong>
                  {f.severity ? ` (${f.severity})` : ""}: {f.message || JSON.stringify(f)}
                </li>
              ))}
            </ul>
          )}
          <pre style={{ background: "#111", color: "#ddd", padding: 16, overflow: "auto" }}>
            {JSON.stringify(
              {
                coverage: report.coverage,
                label_cost: report.label_cost,
                money_opportunities_usd: report.money_opportunities_usd,
                findings: report.findings,
              },
              null,
              2,
            )}
          </pre>
        </>
      )}

      <AuditSynthesisView synthesis={synthesis} viz={viz} />
    </div>
  );
}

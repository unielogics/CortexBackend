import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "./api";

export default function App() {
  const [name, setName] = useState("");
  const [created, setCreated] = useState(null);
  const [err, setErr] = useState("");

  async function create() {
    setErr("");
    try {
      const j = await api("/v1/assessment/engagements", {
        method: "POST",
        body: JSON.stringify({ name: name || "Demo engagement" }),
      });
      setCreated(j);
    } catch (e) {
      setErr(String(e.message));
    }
  }

  return (
    <div style={{ fontFamily: "system-ui", maxWidth: 720, margin: "2rem auto", padding: 24 }}>
      <h1>Unie Cortex</h1>
      <p>Pre-conversion warehouse audit — upload labels/tasks, map columns, run spine, view savings.</p>
      <p style={{ fontSize: 14 }}>
        <Link to="/pro">Product research &amp; item intelligence</Link>
      </p>
      <input
        placeholder="Engagement name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        style={{ padding: 8, width: 280, marginRight: 8 }}
      />
      <button type="button" onClick={create}>
        Create engagement
      </button>
      {err && <p style={{ color: "coral" }}>{err}</p>}
      {created && (
        <p>
          Created <Link to={`/e/${created.engagement_id}`}>{created.engagement_id}</Link> ·{" "}
          <Link to={`/e/${created.engagement_id}/planning`}>Order-financial planning run</Link>
        </p>
      )}
    </div>
  );
}

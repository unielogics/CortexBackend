function tableBase() {
  return { width: "100%", borderCollapse: "collapse", fontSize: 13 };
}

/**
 * Renders placement_mock_rate_grids.rate_shopping_execution_summary (and legacy last_mile fallback).
 */
export default function RateShoppingExecutionSummary({ rss, lastMile }) {
  if (rss && typeof rss === "object" && rss.schema_version) {
    const dim = rss.dimensions || {};
    const wins = rss.states_where_each_warehouse_is_demand_weighted_primary;
    const winEntries = wins && typeof wins === "object" ? Object.entries(wins) : [];
    return (
      <div
        style={{
          marginBottom: 16,
          padding: "14px 16px",
          borderRadius: 8,
          border: "1px solid #cbd5e1",
          background: "#f8fafc",
        }}
      >
        <h3 style={{ margin: "0 0 10px", fontSize: 14 }}>Mock rate shopping (this run)</h3>
        <p style={{ margin: "0 0 12px", fontSize: 13, lineHeight: 1.55, color: "#334155" }}>
          <strong>{rss.mock_parcel_od_cells_evaluated ?? "—"}</strong> origin×state hub O/D evaluations (each runs all
          carrier mocks and picks the cheapest). <strong>{rss.carrier_quote_comparisons_executed ?? "—"}</strong> total
          carrier-level quotes considered (
          <code>
            {dim.origin_warehouse_count ?? "?"}×{dim.state_hub_destinations ?? "?"}×{dim.carriers_evaluated_per_od_cell ?? "?"}
          </code>
          ).
        </p>
        {rss.formula_human && (
          <p style={{ margin: "0 0 12px", fontSize: 12, color: "#475569", lineHeight: 1.5 }}>{rss.formula_human}</p>
        )}
        {dim.carrier_codes && dim.carrier_codes.length > 0 && (
          <p style={{ margin: "0 0 12px", fontSize: 12, color: "#64748b" }}>
            Carriers in mock stack:{" "}
            {dim.carrier_codes.map((c) => (
              <code key={c} style={{ marginRight: 6 }}>
                {c}
              </code>
            ))}
          </p>
        )}
        <div
          style={{
            marginBottom: 12,
            padding: "10px 12px",
            borderRadius: 6,
            background: "#fff",
            border: "1px solid #e2e8f0",
            fontSize: 12,
            lineHeight: 1.55,
            color: "#1e293b",
          }}
        >
          <strong>Primary ship-from per state (intelligence)</strong> — mode{" "}
          <code>{rss.state_primary_assignment_mode ?? "—"}</code>
          <p style={{ margin: "8px 0 0" }}>{rss.how_primary_ship_from_dc_is_chosen_per_state}</p>
        </div>
        {winEntries.length > 0 && (
          <div style={{ overflow: "auto" }}>
            <table style={tableBase()}>
              <thead>
                <tr style={{ background: "#e2e8f0", textAlign: "left" }}>
                  <th style={{ padding: 8 }}>Warehouse</th>
                  <th style={{ padding: 8 }}>
                    {rss.state_primary_assignment_mode === "distance_tie_band"
                      ? "States where this DC is primary (distance + midpoint tie band)"
                      : "States where this DC wins (lowest mock parcel $ to state hub)"}
                  </th>
                </tr>
              </thead>
              <tbody>
                {winEntries.map(([wid, n]) => (
                  <tr key={wid} style={{ borderTop: "1px solid #e2e8f0" }}>
                    <td style={{ padding: 8, fontFamily: "monospace", fontSize: 12 }}>{wid}</td>
                    <td style={{ padding: 8, fontVariantNumeric: "tabular-nums" }}>{n}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p style={{ margin: "8px 0 0", fontSize: 11, color: "#64748b" }}>
              Same regions as in <code>state_demand_primary_warehouse_id</code> /{" "}
              <code>warehouses_routing_summary.states_served</code> — demand weights then roll these primaries into
              network-level metrics and share merge.
            </p>
          </div>
        )}
        {rss.note && (
          <p style={{ margin: "12px 0 0", fontSize: 11, color: "#64748b", lineHeight: 1.45 }}>{rss.note}</p>
        )}
      </div>
    );
  }
  if (lastMile?.estimated_mock_parcel_carrier_comparisons != null) {
    return (
      <p style={{ margin: "0 0 10px", fontSize: 12, color: "#475569", lineHeight: 1.5 }}>
        Mock parcel work this run: ~ <strong>{lastMile.estimated_mock_parcel_carrier_comparisons}</strong> carrier
        comparisons (warehouses × state hubs × carriers). {lastMile.quote_topology_note}
      </p>
    );
  }
  return null;
}

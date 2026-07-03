"use client";

import { useEffect, useState } from "react";

type Snapshot = {
  id?: number;
  created_at?: string;
  window_days: number;
  deploy_freq: number;
  lead_time_p50: number;
  cfr: number;
  mttr_p50: number;
  tier: string;
};

type Heuristic = {
  id: string;
  rule: string;
  why: string;
  use_count: number;
  source: string;
  tags: string[];
  score: number;
  domain: string;
  created_at: string;
};

function tierColor(tier: string): string {
  const map: Record<string, string> = {
    Elite: "#22c55e",
    High: "#3b82f6",
    Medium: "#f59e0b",
    Low: "#ef4444",
  };
  return map[tier] ?? "#6b7280";
}

function MetricCard({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div
      className="card"
      style={{
        background: "var(--bg-secondary)",
        borderRadius: 8,
        padding: "16px 20px",
        minWidth: 140,
      }}
    >
      <div
        style={{
          fontSize: 11,
          textTransform: "uppercase",
          letterSpacing: "0.08em",
          color: "var(--text-muted)",
          marginBottom: 4,
        }}
      >
        {label}
      </div>
      <div style={{ fontSize: 22, fontWeight: 700 }}>{value}</div>
      {sub && (
        <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
          {sub}
        </div>
      )}
    </div>
  );
}

export default function DoraPage() {
  const [data, setData] = useState<{
    latest: Snapshot;
    history: Snapshot[];
  } | null>(null);
  const [heur, setHeur] = useState<{
    active: Heuristic[];
    candidates: Heuristic[];
  } | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      fetch("/api/dora").then((r) => r.json()),
      fetch("/api/heuristics").then((r) => r.json()),
    ])
      .then(([d, h]) => {
        setData(d);
        setHeur(h);
      })
      .catch((e) => setErr(String(e)));
  }, []);

  if (err)
    return (
      <div className="p-6" style={{ color: "var(--text-muted)" }}>
        Error: {err}
      </div>
    );
  if (!data || !heur)
    return (
      <div className="p-6" style={{ color: "var(--text-muted)" }}>
        Loading...
      </div>
    );

  const s = data.latest;
  const history = [...data.history].reverse();

  return (
    <div className="space-y-6" style={{ padding: "24px 32px" }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
        <h1 style={{ fontSize: 22, fontWeight: 700 }}>DORA Metrics</h1>
        <span
          style={{
            background: tierColor(s.tier),
            color: "#fff",
            borderRadius: 6,
            padding: "2px 10px",
            fontSize: 13,
            fontWeight: 600,
          }}
        >
          {s.tier}
        </span>
        <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
          window: {s.window_days}d
        </span>
      </div>

      {/* Metric cards */}
      <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
        <MetricCard
          label="Deploy freq"
          value={`${s.deploy_freq.toFixed(2)}/d`}
          sub="deploys per day"
        />
        <MetricCard
          label="Lead time p50"
          value={`${(s.lead_time_p50 / 3600).toFixed(1)}h`}
          sub="commit → deploy"
        />
        <MetricCard
          label="CFR"
          value={`${(s.cfr * 100).toFixed(1)}%`}
          sub="change fail rate"
        />
        <MetricCard
          label="MTTR p50"
          value={`${(s.mttr_p50 / 3600).toFixed(1)}h`}
          sub="mean time to restore"
        />
      </div>

      {/* History table */}
      <section>
        <h2
          style={{
            fontSize: 15,
            fontWeight: 600,
            marginBottom: 8,
          }}
        >
          Snapshot history ({history.length})
        </h2>
        {history.length === 0 ? (
          <div style={{ color: "var(--text-muted)", fontSize: 13 }}>
            No snapshots stored yet.
          </div>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table
              style={{
                width: "100%",
                fontSize: 13,
                borderCollapse: "collapse",
              }}
            >
              <thead>
                <tr
                  style={{
                    color: "var(--text-muted)",
                    borderBottom: "1px solid var(--border)",
                  }}
                >
                  {[
                    "Date",
                    "Tier",
                    "Deploy/d",
                    "Lead p50 (h)",
                    "CFR",
                    "MTTR p50 (h)",
                  ].map((h) => (
                    <th
                      key={h}
                      style={{ textAlign: "left", padding: "4px 10px" }}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {history.map((row, i) => (
                  <tr
                    key={i}
                    style={{ borderBottom: "1px solid var(--border)" }}
                  >
                    <td style={{ padding: "5px 10px" }}>
                      {row.created_at ? row.created_at.slice(0, 10) : "—"}
                    </td>
                    <td style={{ padding: "5px 10px" }}>
                      <span
                        style={{
                          color: tierColor(row.tier),
                          fontWeight: 600,
                        }}
                      >
                        {row.tier}
                      </span>
                    </td>
                    <td style={{ padding: "5px 10px" }}>
                      {row.deploy_freq.toFixed(2)}
                    </td>
                    <td style={{ padding: "5px 10px" }}>
                      {(row.lead_time_p50 / 3600).toFixed(1)}
                    </td>
                    <td style={{ padding: "5px 10px" }}>
                      {(row.cfr * 100).toFixed(1)}%
                    </td>
                    <td style={{ padding: "5px 10px" }}>
                      {(row.mttr_p50 / 3600).toFixed(1)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Candidate heuristics */}
      <section>
        <h2 style={{ fontSize: 15, fontWeight: 600, marginBottom: 8 }}>
          Candidate heuristics ({heur.candidates.length})
        </h2>
        {heur.candidates.length === 0 ? (
          <div style={{ color: "var(--text-muted)", fontSize: 13 }}>None.</div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {heur.candidates.map((h) => (
              <div
                key={h.id}
                style={{
                  background: "var(--bg-secondary)",
                  borderRadius: 8,
                  padding: "10px 14px",
                  fontSize: 13,
                }}
              >
                <div style={{ fontWeight: 600, fontFamily: "monospace" }}>
                  {h.rule}
                </div>
                <div
                  style={{ color: "var(--text-muted)", marginTop: 2 }}
                >
                  {h.why}
                </div>
                <div style={{ marginTop: 4, fontSize: 11, color: "var(--text-muted)" }}>
                  tags: {h.tags.join(", ")} &nbsp;|&nbsp; score:{" "}
                  {h.score.toFixed(2)} &nbsp;|&nbsp; source: {h.source}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Active heuristics */}
      <section>
        <h2 style={{ fontSize: 15, fontWeight: 600, marginBottom: 8 }}>
          Active heuristics ({heur.active.length})
        </h2>
        {heur.active.length === 0 ? (
          <div style={{ color: "var(--text-muted)", fontSize: 13 }}>None.</div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {heur.active.map((h) => (
              <div
                key={h.id}
                style={{
                  background: "var(--bg-secondary)",
                  borderRadius: 8,
                  padding: "10px 14px",
                  fontSize: 13,
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "flex-start",
                  gap: 12,
                }}
              >
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 600, fontFamily: "monospace" }}>
                    {h.rule}
                  </div>
                  <div style={{ color: "var(--text-muted)", marginTop: 2 }}>
                    {h.why}
                  </div>
                </div>
                <div
                  style={{
                    fontSize: 11,
                    color: "var(--text-muted)",
                    whiteSpace: "nowrap",
                  }}
                >
                  used {h.use_count}x
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

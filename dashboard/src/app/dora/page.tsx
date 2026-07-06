"use client";

import { useEffect, useState } from "react";
import { Heading, Card, Badge } from "@/lib/ui";

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

function MetricCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <Card className="flex-1 text-center" style={{ background: "var(--bg-secondary)", borderRadius: 8 }}>
      <div className="text-[11px] uppercase tracking-widest mb-1" style={{ color: "var(--text-muted)" }}>{label}</div>
      <div className="text-[22px] font-bold" style={{ color: "var(--text-primary)" }}>{value}</div>
      {sub && <div className="text-[11px] mt-0.5" style={{ color: "var(--text-muted)" }}>{sub}</div>}
    </Card>
  );
}

export default function DoraPage() {
  const [data, setData] = useState<{ latest: Snapshot; history: Snapshot[] } | null>(null);
  const [heur, setHeur] = useState<{ active: Heuristic[]; candidates: Heuristic[] } | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      fetch("/api/dora").then((r) => r.json()),
      fetch("/api/heuristics").then((r) => r.json()),
    ])
      .then(([d, h]) => { setData(d); setHeur(h); })
      .catch((e) => setErr(String(e)));
  }, []);

  if (err) return <div className="px-6 py-6" style={{ color: "var(--text-muted)" }}>Error: {err}</div>;
  if (!data || !heur) return <div className="px-6 py-6" style={{ color: "var(--text-muted)" }}>Loading...</div>;

  const s = data.latest;
  const history = [...data.history].reverse();

  return (
    <div className="px-6 py-6 space-y-8">
      <div className="flex items-center gap-4">
        <Heading level={1}>DORA Metrics</Heading>
        <span style={{ background: tierColor(s.tier), color: "#fff", borderRadius: 6, padding: "2px 10px", fontSize: 13, fontWeight: 600 }}>
          {s.tier}
        </span>
        <span className="text-xs" style={{ color: "var(--text-muted)" }}>window: {s.window_days}d</span>
      </div>

      <div className="flex gap-4 flex-wrap">
        <MetricCard label="Deploy freq" value={`${s.deploy_freq.toFixed(2)}/d`} sub="deploys per day" />
        <MetricCard label="Lead time p50" value={`${(s.lead_time_p50 / 3600).toFixed(1)}h`} sub="commit → deploy" />
        <MetricCard label="CFR" value={`${(s.cfr * 100).toFixed(1)}%`} sub="change fail rate" />
        <MetricCard label="MTTR p50" value={`${(s.mttr_p50 / 3600).toFixed(1)}h`} sub="mean time to restore" />
      </div>

      <section>
        <Heading level={2}>Snapshot history ({history.length})</Heading>
        {history.length === 0 ? (
          <div className="text-sm mt-2" style={{ color: "var(--text-muted)" }}>No snapshots stored yet.</div>
        ) : (
          <Card className="overflow-x-auto p-0 mt-2">
            <table style={{ width: "100%", fontSize: 13, borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ borderBottom: "1px solid var(--border)", color: "var(--text-muted)" }}>
                  {["Date","Tier","Deploy/d","Lead p50 (h)","CFR","MTTR p50 (h)"].map(h => (
                    <th key={h} className="px-3 py-2 text-left text-xs font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {history.map((row, i) => (
                  <tr key={i} className="border-b border-[var(--border)] hover:bg-[var(--bg-secondary)] transition-colors">
                    <td className="px-3 py-2">{row.created_at ? row.created_at.slice(0, 10) : "—"}</td>
                    <td className="px-3 py-2"><span style={{ color: tierColor(row.tier), fontWeight: 600 }}>{row.tier}</span></td>
                    <td className="px-3 py-2">{row.deploy_freq.toFixed(2)}</td>
                    <td className="px-3 py-2">{(row.lead_time_p50 / 3600).toFixed(1)}</td>
                    <td className="px-3 py-2">{(row.cfr * 100).toFixed(1)}%</td>
                    <td className="px-3 py-2">{(row.mttr_p50 / 3600).toFixed(1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        )}
      </section>

      <section>
        <Heading level={2}>Candidate heuristics ({heur.candidates.length})</Heading>
        {heur.candidates.length === 0 ? (
          <div className="text-sm mt-2" style={{ color: "var(--text-muted)" }}>None.</div>
        ) : (
          <div className="space-y-2 mt-2">
            {heur.candidates.map((h) => (
              <Card key={h.id} style={{ background: "var(--bg-secondary)", borderRadius: 8 }}>
                <div className="font-mono text-sm font-semibold" style={{ color: "var(--text-primary)" }}>{h.rule}</div>
                <div className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>{h.why}</div>
                <div className="text-[11px] mt-2" style={{ color: "var(--text-muted)" }}>
                  tags: {h.tags.join(", ")} | score: {h.score.toFixed(2)} | source: {h.source}
                </div>
              </Card>
            ))}
          </div>
        )}
      </section>

      <section>
        <Heading level={2}>Active heuristics ({heur.active.length})</Heading>
        {heur.active.length === 0 ? (
          <div className="text-sm mt-2" style={{ color: "var(--text-muted)" }}>None.</div>
        ) : (
          <div className="space-y-2 mt-2">
            {heur.active.map((h) => (
              <Card key={h.id} style={{ background: "var(--bg-secondary)", borderRadius: 8 }}>
                <div className="flex justify-between items-start gap-3">
                  <div className="flex-1">
                    <div className="font-mono text-sm font-semibold" style={{ color: "var(--text-primary)" }}>{h.rule}</div>
                    <div className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>{h.why}</div>
                  </div>
                  <div className="text-[11px] shrink-0" style={{ color: "var(--text-muted)" }}>used {h.use_count}x</div>
                </div>
              </Card>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

"use client";

import { useState } from "react";
import { runStrategist, StrategistResult } from "@/lib/api";

const EXAMPLES = [
  "Find non-obvious cointegrated equity pairs outside the same sector — shared commodity or supply-chain links.",
  "Rates are shifting — look for cointegration among rate-sensitive names across REITs, utilities, and regional banks.",
  "Hunt durable cointegration in large-cap crypto beyond the obvious BTC-beta plays.",
];

export default function Strategist() {
  const [objective, setObjective] = useState("");
  const [assetClass, setAssetClass] = useState("equity");
  const [research, setResearch] = useState(false);
  const [result, setResult] = useState<StrategistResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState(false);

  const run = async () => {
    if (!objective.trim() || loading) return;
    setLoading(true); setErr(false); setResult(null);
    try { setResult(await runStrategist(objective, assetClass, research)); }
    catch { setErr(true); }
    finally { setLoading(false); }
  };

  return (
    <div className="max-w-3xl mx-auto">
      <h1 className="text-2xl font-semibold tracking-tight mb-1">Strategist</h1>
      <p className="text-sm mb-5" style={{ color: "var(--text-muted)" }}>
        Give the agent an objective. It <b>reasons</b> about where non-obvious cointegration might live,
        <b> proposes</b> its own ticker universes, <b>tests</b> each with the scanner, and reports —
        no hardcoded universe. {research && "Research spawns the analyst department (slow)."}
      </p>

      <div className="card mb-4">
        <textarea className="input w-full" rows={3} placeholder="e.g. shared-commodity pairs across airlines and refiners…"
          value={objective} onChange={(e) => setObjective(e.target.value)} style={{ resize: "vertical" }} />
        <div className="flex flex-wrap gap-1.5 mt-2">
          {EXAMPLES.map((ex, i) => (
            <button key={i} className="badge badge-gray" style={{ cursor: "pointer" }}
              onClick={() => setObjective(ex)}>{ex.slice(0, 38)}…</button>
          ))}
        </div>
        <div className="flex items-center gap-3 mt-3 flex-wrap">
          <select className="input" value={assetClass} onChange={(e) => setAssetClass(e.target.value)}>
            <option value="equity">equity</option>
            <option value="crypto">crypto</option>
          </select>
          <label className="text-sm flex items-center gap-1.5" style={{ color: "var(--text-secondary)" }}>
            <input type="checkbox" checked={research} onChange={(e) => setResearch(e.target.checked)} />
            spawn research (slow)
          </label>
          <button className="btn btn-primary ml-auto" onClick={run} disabled={loading || !objective.trim()}>
            {loading ? "Thinking…" : "Dispatch ▸"}
          </button>
        </div>
      </div>

      {loading && (
        <div className="card text-sm" style={{ color: "var(--text-muted)" }}>
          The strategist is reasoning, proposing universes, and scanning each one — this runs for a
          minute or two (longer with research). It works autonomously; the result lands here when done.
        </div>
      )}
      {err && !loading && (
        <div className="card" style={{ borderColor: "var(--red)" }}>
          <span style={{ color: "var(--red)" }}>The strategist run failed or timed out.</span>
        </div>
      )}
      {result && !loading && (
        <div className="card">
          <div className="flex items-center gap-2 mb-2">
            <span className={result.status === "completed" ? "badge badge-green" : "badge badge-yellow"}>
              {result.status}
            </span>
            {result.tokens != null && <span className="text-xs" style={{ color: "var(--text-muted)" }}>
              {result.tokens.toLocaleString()} tokens</span>}
          </div>
          <div className="text-sm whitespace-pre-wrap" style={{ color: "var(--text-primary)", lineHeight: 1.6 }}>
            {result.summary}
          </div>
          {result.notes && <div className="text-xs mt-3" style={{ color: "var(--text-muted)" }}>{result.notes}</div>}
        </div>
      )}
      {!result && !loading && !err && (
        <div className="text-sm" style={{ color: "var(--text-muted)" }}>
          Pick an example or write your own thesis, then dispatch the agent.
        </div>
      )}
    </div>
  );
}

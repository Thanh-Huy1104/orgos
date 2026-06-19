"use client";

import { useState } from "react";
import { startStrategist, getStrategistJob, StrategistResult } from "@/lib/api";
import { Trail, Digest, RunTrail } from "@/lib/trail";

const EXAMPLES = [
  "Find non-obvious cointegrated equity pairs outside the same sector — shared commodity or supply-chain links.",
  "Rates are shifting — look for cointegration among rate-sensitive names across REITs, utilities, and regional banks.",
  "Hunt durable cointegration in large-cap crypto beyond the obvious BTC-beta plays.",
];

export default function Strategist() {
  const [objective, setObjective] = useState("");
  const [assetClass, setAssetClass] = useState("equity");
  const [research, setResearch] = useState(false);
  const [maxAttempts, setMaxAttempts] = useState(2);
  const [result, setResult] = useState<StrategistResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [err, setErr] = useState(false);

  // Hunts run for minutes, so we dispatch a background job and poll it. The run
  // keeps going (and lands in the Journal) even if this page is closed.
  const run = async () => {
    if (!objective.trim() || loading) return;
    setLoading(true); setErr(false); setResult(null); setElapsed(0);
    const t0 = Date.now();
    try {
      const { job_id } = await startStrategist(objective, assetClass, research, maxAttempts);
      for (;;) {
        await new Promise((r) => setTimeout(r, 3000));
        setElapsed(Math.round((Date.now() - t0) / 1000));
        const job = await getStrategistJob(job_id);
        if (job.status === "done" && job.result) { setResult(job.result); break; }
        if (job.status === "error") { setErr(true); break; }
        if (Date.now() - t0 > 20 * 60 * 1000) { setErr(true); break; }  // safety cap
      }
    } catch { setErr(true); }
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
          <label className="text-sm flex items-center gap-1.5" style={{ color: "var(--text-secondary)" }}>
            attempts
            <select className="input" value={maxAttempts} onChange={(e) => setMaxAttempts(Number(e.target.value))} style={{ width: 52, padding: "2px 4px" }}>
              <option value={1}>1</option>
              <option value={2}>2</option>
              <option value={3}>3</option>
              <option value={5}>5</option>
            </select>
          </label>
          <button className="btn btn-primary ml-auto" onClick={run} disabled={loading || !objective.trim()}>
            {loading ? "Running…" : "Dispatch ▸"}
          </button>
        </div>
      </div>

      {loading && (
        <div className="card text-sm" style={{ color: "var(--text-muted)" }}>
          Dispatched — the strategist is reasoning, proposing universes, and scanning each one.
          This runs for several minutes{maxAttempts > 1 ? ` (×${maxAttempts} attempts, keeping the best)` : ""}.
          <span style={{ color: "var(--text-secondary)" }}> {elapsed}s elapsed.</span> It runs in the
          background — you can leave; the result also lands in the Journal.
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
          {result.rubric && (
            <div className="flex items-center gap-2 mb-2 flex-wrap text-xs">
              <span className={result.rubric.passed ? "badge badge-green" : "badge badge-yellow"}>
                rubric {result.rubric.passed ? "✓ met" : "✗ not met"}
              </span>
              <span style={{ color: "var(--text-muted)" }}>strength {result.rubric.score.toFixed(4)}</span>
              {result.attempts != null && (
                <span style={{ color: "var(--text-muted)" }}>
                  · {result.attempts} attempt{result.attempts === 1 ? "" : "s"}
                </span>
              )}
              {result.rubric.notes && (
                <span style={{ color: "var(--text-muted)" }}>· {result.rubric.notes}</span>
              )}
            </div>
          )}
          {result.trail && <Digest steps={result.trail} />}
          <div className="text-sm whitespace-pre-wrap mt-2" style={{ color: "var(--text-primary)", lineHeight: 1.6 }}>
            {result.summary}
          </div>
          {result.notes && <div className="text-xs mt-3" style={{ color: "var(--text-muted)" }}>{result.notes}</div>}
        </div>
      )}
      {result && !loading && result.trail && (
        <div className="card mt-4">
          <div className="text-sm font-medium mb-1">
            Research trail <span style={{ color: "var(--text-muted)" }}>· kept run, {result.trail.length} tool calls</span>
          </div>
          <Trail steps={result.trail} />
          {(result.attempt_run_ids ?? []).filter((id) => id !== result.run_id).length > 0 && (
            <div className="mt-2">
              <div className="text-xs mb-0.5" style={{ color: "var(--text-muted)" }}>
                other attempts — the runs it tried before keeping the best
              </div>
              {(result.attempt_run_ids ?? [])
                .filter((id) => id !== result.run_id)
                .map((id, i) => <RunTrail key={id} runId={id} label={`attempt ${i + 1}`} />)}
            </div>
          )}
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

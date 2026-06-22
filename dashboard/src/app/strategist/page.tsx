"use client";

import { useState } from "react";
import {
  startStrategist, getStrategistJob,
  startOptionsStrategist, getOptionsStrategistJob,
  StrategistResult,
} from "@/lib/api";
import { Trail, Digest, RunTrail } from "@/lib/trail";

const PAIRS_EXAMPLES = [
  "Find non-obvious cointegrated equity pairs outside the same sector — shared commodity or supply-chain links.",
  "Rates are shifting — look for cointegration among rate-sensitive names across REITs, utilities, and regional banks.",
  "Hunt durable cointegration in large-cap crypto beyond the obvious BTC-beta plays.",
];

const OPTIONS_EXAMPLES = [
  "Find an options strategy on a tech stock with upcoming earnings — expect a big move.",
  "High VIX environment — look for premium-selling opportunities on stable large-caps.",
  "Bearish thesis on energy sector — find cheap puts with asymmetric payoff.",
];

type Mode = "pairs" | "options";
type View = "neutral" | "bullish" | "bearish" | "volatile";

export default function Strategist() {
  const [mode, setMode] = useState<Mode>("pairs");

  // Shared
  const [objective, setObjective] = useState("");
  const [maxAttempts, setMaxAttempts] = useState(2);
  const [result, setResult] = useState<StrategistResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [err, setErr] = useState(false);

  // Pairs-only
  const [assetClass, setAssetClass] = useState("equity");
  const [research, setResearch] = useState(false);

  // Options-only
  const [view, setView] = useState<View>("neutral");

  const switchMode = (m: Mode) => {
    setMode(m);
    setObjective("");
    setResult(null);
    setErr(false);
  };

  const run = async () => {
    if (!objective.trim() || loading) return;
    setLoading(true); setErr(false); setResult(null); setElapsed(0);
    const t0 = Date.now();
    try {
      if (mode === "pairs") {
        const { job_id } = await startStrategist(objective, assetClass, research, maxAttempts);
        for (;;) {
          await new Promise((r) => setTimeout(r, 3000));
          setElapsed(Math.round((Date.now() - t0) / 1000));
          const job = await getStrategistJob(job_id);
          if (job.status === "done" && job.result) { setResult(job.result); break; }
          if (job.status === "error") { setErr(true); break; }
          if (Date.now() - t0 > 20 * 60 * 1000) { setErr(true); break; }
        }
      } else {
        const { job_id } = await startOptionsStrategist(objective, view, maxAttempts);
        for (;;) {
          await new Promise((r) => setTimeout(r, 3000));
          setElapsed(Math.round((Date.now() - t0) / 1000));
          const job = await getOptionsStrategistJob(job_id);
          if (job.status === "done" && job.result) { setResult(job.result); break; }
          if (job.status === "error") { setErr(true); break; }
          if (Date.now() - t0 > 20 * 60 * 1000) { setErr(true); break; }
        }
      }
    } catch { setErr(true); }
    finally { setLoading(false); }
  };

  const examples = mode === "pairs" ? PAIRS_EXAMPLES : OPTIONS_EXAMPLES;

  return (
    <div className="max-w-3xl mx-auto">
      <h1 className="text-2xl font-semibold tracking-tight mb-1">Strategist</h1>

      {/* Mode toggle */}
      <div className="flex gap-1 mb-4" style={{ borderBottom: "1px solid var(--border)" }}>
        {(["pairs", "options"] as Mode[]).map((m) => (
          <button
            key={m}
            onClick={() => switchMode(m)}
            className="text-sm px-3 py-1.5"
            style={{
              borderBottom: mode === m ? "2px solid var(--accent)" : "2px solid transparent",
              color: mode === m ? "var(--text-primary)" : "var(--text-muted)",
              background: "none",
              cursor: "pointer",
              fontWeight: mode === m ? 600 : 400,
            }}
          >
            {m === "pairs" ? "Pair Hunting" : "Options Edge"}
          </button>
        ))}
      </div>

      <p className="text-sm mb-5" style={{ color: "var(--text-muted)" }}>
        {mode === "pairs" ? (
          <>
            The agent <b>reasons</b> about where non-obvious cointegration might live,
            <b> proposes</b> its own ticker universes, <b>tests</b> each with the scanner, and reports —
            no hardcoded universe. {research && "Research spawns the analyst department (slow)."}
          </>
        ) : (
          <>
            The agent scans <b>news catalysts</b> for candidate tickers, runs <b>IV surface</b> and
            <b> vol</b> scans for each, and recommends a defined-risk options structure only when
            a structural edge exists — IV rank in a tradeable zone with a non-neutral vol signal.
          </>
        )}
      </p>

      <div className="card mb-4">
        <textarea
          className="input w-full" rows={3}
          placeholder={mode === "pairs"
            ? "e.g. shared-commodity pairs across airlines and refiners…"
            : "e.g. find an iron condor on a stable large-cap with high IV rank…"}
          value={objective}
          onChange={(e) => setObjective(e.target.value)}
          style={{ resize: "vertical" }}
        />
        <div className="flex flex-wrap gap-1.5 mt-2">
          {examples.map((ex, i) => (
            <button key={i} className="badge badge-gray" style={{ cursor: "pointer" }}
              onClick={() => setObjective(ex)}>{ex.slice(0, 42)}…</button>
          ))}
        </div>

        <div className="flex items-center gap-3 mt-3 flex-wrap">
          {mode === "pairs" ? (
            <>
              <select className="input" value={assetClass} onChange={(e) => setAssetClass(e.target.value)}>
                <option value="equity">equity</option>
                <option value="crypto">crypto</option>
              </select>
              <label className="text-sm flex items-center gap-1.5" style={{ color: "var(--text-secondary)" }}>
                <input type="checkbox" checked={research} onChange={(e) => setResearch(e.target.checked)} />
                spawn research (slow)
              </label>
            </>
          ) : (
            <select className="input" value={view} onChange={(e) => setView(e.target.value as View)}>
              <option value="neutral">neutral</option>
              <option value="bullish">bullish</option>
              <option value="bearish">bearish</option>
              <option value="volatile">volatile (big move)</option>
            </select>
          )}

          <label className="text-sm flex items-center gap-1.5" style={{ color: "var(--text-secondary)" }}>
            attempts
            <select className="input" value={maxAttempts} onChange={(e) => setMaxAttempts(Number(e.target.value))}
              style={{ width: 52, padding: "2px 4px" }}>
              <option value={1}>1</option>
              <option value={2}>2</option>
              <option value={3}>3</option>
            </select>
          </label>

          <button className="btn btn-primary ml-auto" onClick={run} disabled={loading || !objective.trim()}>
            {loading ? "Running…" : "Dispatch ▸"}
          </button>
        </div>
      </div>

      {loading && (
        <div className="card text-sm" style={{ color: "var(--text-muted)" }}>
          {mode === "pairs"
            ? "Dispatched — the strategist is reasoning, proposing universes, and scanning each one."
            : "Dispatched — scanning news catalysts, running IV surface analysis, and building the strategy handoff."}
          {" "}This runs for several minutes{maxAttempts > 1 ? ` (×${maxAttempts} attempts, keeping the best)` : ""}.
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
            {result.tokens != null && (
              <span className="text-xs" style={{ color: "var(--text-muted)" }}>
                {result.tokens.toLocaleString()} tokens
              </span>
            )}
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
          {result.notes && (
            <div className="text-xs mt-3" style={{ color: "var(--text-muted)" }}>{result.notes}</div>
          )}
        </div>
      )}

      {result && !loading && result.trail && (
        <div className="card mt-4">
          <div className="text-sm font-medium mb-1">
            Research trail{" "}
            <span style={{ color: "var(--text-muted)" }}>· {result.trail.length} tool calls</span>
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

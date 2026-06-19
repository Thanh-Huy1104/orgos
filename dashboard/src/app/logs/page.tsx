"use client";

import { useEffect, useState } from "react";
import { TrailRun, TrailStep, getTrails, getTrail } from "@/lib/api";
import { Trail, Digest } from "@/lib/trail";

function RunRow({ run }: { run: TrailRun }) {
  const [trail, setTrail] = useState<TrailStep[] | null>(null);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    if (trail || loading) return;
    setLoading(true);
    try { setTrail((await getTrail(run.run_id)).trail); }
    catch { setTrail([]); }
    finally { setLoading(false); }
  };

  return (
    <details className="card" onToggle={(ev) => (ev.currentTarget as HTMLDetailsElement).open && load()}>
      <summary className="flex items-center gap-3 flex-wrap" style={{ cursor: "pointer" }}>
        <span className="font-mono text-sm" style={{ color: "var(--text-primary)" }}>{run.run_id}</span>
        <span className="badge badge-gray">{run.tool_calls} calls</span>
        {run.tool_calls > 0 && run.ok < run.tool_calls && (
          <span className="badge badge-yellow">{run.tool_calls - run.ok} errored</span>
        )}
        <span className="text-xs ml-auto" style={{ color: "var(--text-muted)" }}>
          {new Date(run.ts).toLocaleString()}{loading ? " · loading…" : ""}
        </span>
      </summary>
      {trail && <><Digest steps={trail} /><Trail steps={trail} /></>}
    </details>
  );
}

export default function LogsPage() {
  const [runs, setRuns] = useState<TrailRun[] | null>(null);
  const [err, setErr] = useState(false);

  useEffect(() => { getTrails(40).then((r) => setRuns(r.runs)).catch(() => setErr(true)); }, []);

  return (
    <div className="max-w-3xl mx-auto">
      <h1 className="text-2xl font-semibold tracking-tight mb-1">Logs</h1>
      <p className="text-sm mb-5" style={{ color: "var(--text-muted)" }}>
        The research trail of every recent run — exactly what each agent read, scanned, and tested,
        with inputs and outputs. Expand a run to see its tool-by-tool log.
      </p>

      {err && <div className="card" style={{ borderColor: "var(--red)" }}>
        <span style={{ color: "var(--red)" }}>Couldn&apos;t load run logs.</span>
      </div>}
      {runs && runs.length === 0 && (
        <div className="card text-sm" style={{ color: "var(--text-muted)" }}>No runs with a trail yet.</div>
      )}
      {runs && runs.length > 0 && (
        <div className="flex flex-col gap-2">
          {runs.map((r) => <RunRow key={r.run_id} run={r} />)}
        </div>
      )}
    </div>
  );
}

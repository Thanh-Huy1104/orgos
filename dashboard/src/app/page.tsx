"use client";

import { useEffect, useState } from "react";
import { DashboardData, getDashboard, runScheduler, createProject } from "@/lib/api";

function Badge({ status, label }: { status: string; label?: string }) {
  const cls: Record<string, string> = {
    completed: "badge badge-green", failed: "badge badge-red", blocked: "badge badge-yellow",
    needs_revision: "badge badge-yellow", active: "badge badge-blue", in_progress: "badge badge-blue",
  };
  return <span className={cls[status] || "badge badge-gray"}>{label || status}</span>;
}

function Stat({ label, value, unit, color }: { label: string; value: string | number; unit?: string; color?: string }) {
  return (
    <div className="card">
      <div className="text-xs" style={{ color: "var(--text-muted)" }}>{label}</div>
      <div className="text-xl font-semibold mt-1" style={color ? { color } : {}}>
        {typeof value === "number" ? value.toLocaleString() : value}
        {unit && <span className="text-xs font-normal ml-1" style={{ color: "var(--text-muted)" }}>{unit}</span>}
      </div>
    </div>
  );
}

export default function Dashboard() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [goal, setGoal] = useState("");
  const [loading, setLoading] = useState(true);
  const [msg, setMsg] = useState("");
  const [creating, setCreating] = useState(false);

  const refresh = () => getDashboard().then(setData).catch(() => {}).finally(() => setLoading(false));
  useEffect(() => { refresh(); }, []);

  const doCreate = async () => {
    if (!goal.trim() || creating) return;
    setCreating(true);
    try {
      const r = await createProject(goal);
      if (r.mode === "simple") setMsg(`[${r.department}] ${r.summary?.slice(0, 300) || r.status}`);
      else setMsg(`Project created: ${r.project_name} (${r.tasks} tasks)`);
      setGoal(""); refresh();
    } catch (e: any) { setMsg(`Error: ${e.message}`); }
    setCreating(false);
  };

  return (
    <div className="space-y-5">
      <h1 className="text-xl font-semibold">Dashboard</h1>

      <div className="card">
        <div className="flex gap-2">
          <input
            className="input flex-1"
            placeholder="Ask anything — what's on my calendar? Scan ETFs? Generate a report?"
            value={goal}
            onChange={e => setGoal(e.target.value)}
            onKeyDown={e => e.key === "Enter" && doCreate()}
          />
          <button className="btn btn-primary" onClick={doCreate} disabled={!goal.trim() || creating}>
            {creating ? "..." : "Send"}
          </button>
        </div>
        {msg && <div className="mt-3 text-sm p-3 rounded-lg" style={{ background: "var(--bg-secondary)", color: "var(--text-secondary)" }}>{msg}</div>}
      </div>

      {!loading && data && (
        <>
          <div className="grid grid-cols-4 gap-3">
            <Stat label="Departments" value={data.departments.length} />
            <Stat label="30-day spend" value={data.total_spend_30d} unit="tokens" />
            <Stat label="30-day runs" value={data.total_runs_30d} />
            <Stat label="Budget" value={data.budget ? `${Math.round(data.total_spend_30d / data.budget * 100)}%` : "—"} color={data.budget && data.total_spend_30d > data.budget * 0.8 ? "var(--red)" : undefined} />
          </div>

          {data.departments.length > 0 && (
            <div className="grid grid-cols-3 gap-3">
              {data.departments.map(d => (
                <div key={d.name} className="card">
                  <div className="flex justify-between items-center">
                    <span className="font-medium text-sm">{d.name}</span>
                    <span className="text-xs" style={{ color: d.success_rate > 80 ? "var(--green)" : "var(--text-muted)" }}>{d.success_rate}%</span>
                  </div>
                  <div className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>{d.spend_7d.toLocaleString()} tokens/7d · {d.recent_runs} runs</div>
                  {d.failures > 0 && <div className="text-xs mt-0.5" style={{ color: "var(--red)" }}>{d.failures} failures</div>}
                </div>
              ))}
            </div>
          )}

          <div className="flex justify-between items-center">
            <h2 className="text-sm font-semibold" style={{ color: "var(--text-secondary)" }}>Recent Activity</h2>
            <button className="btn btn-secondary text-xs" onClick={async () => { await runScheduler(); refresh(); }}>Run Scheduler</button>
          </div>
          <div className="space-y-1">
            {data.recent_activity.slice(0, 12).map(r => (
              <div key={r.id} className="card flex items-center gap-3" style={{ padding: "10px 14px" }}>
                <Badge status={r.status} />
                <div className="flex-1 min-w-0">
                  <div className="text-sm">{r.department}/{r.role}</div>
                  <div className="text-xs truncate" style={{ color: "var(--text-muted)" }}>{r.summary}</div>
                </div>
                <div className="text-xs shrink-0" style={{ color: "var(--text-muted)" }}>{r.tokens.toLocaleString()} tokens</div>
              </div>
            ))}
          </div>

          {data.projects.length > 0 && (
            <>
              <h2 className="text-sm font-semibold" style={{ color: "var(--text-secondary)" }}>Active Projects</h2>
              <div className="grid grid-cols-2 gap-3">
                {data.projects.map(p => (
                  <div key={p.id} className="card">
                    <div className="flex justify-between"><span className="font-medium text-sm">{p.name}</span><Badge status={p.status} /></div>
                    <div className="text-xs mt-1 truncate" style={{ color: "var(--text-muted)" }}>{p.goal}</div>
                  </div>
                ))}
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}

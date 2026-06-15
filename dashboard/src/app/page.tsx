"use client";

import { useEffect, useState } from "react";
import { DashboardData, getDashboard, runScheduler, createProject } from "@/lib/api";
import Link from "next/link";

function Stat({ label, value, unit }: { label: string; value: string | number; unit?: string }) {
  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-4">
      <div className="text-sm text-zinc-500">{label}</div>
      <div className="text-2xl font-bold mt-1">
        {typeof value === "number" ? value.toLocaleString() : value}
        {unit && <span className="text-sm text-zinc-500 ml-1">{unit}</span>}
      </div>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    completed: "bg-green-900/50 text-green-400 border-green-800",
    failed: "bg-red-900/50 text-red-400 border-red-800",
    blocked: "bg-yellow-900/50 text-yellow-400 border-yellow-800",
    needs_revision: "bg-orange-900/50 text-orange-400 border-orange-800",
    active: "bg-blue-900/50 text-blue-400 border-blue-800",
    in_progress: "bg-blue-900/50 text-blue-400 border-blue-800",
  };
  return (
    <span className={`text-xs px-2 py-0.5 rounded border ${colors[status] || "bg-zinc-800 text-zinc-400 border-zinc-700"}`}>
      {status}
    </span>
  );
}

export default function Dashboard() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionMsg, setActionMsg] = useState("");
  const [projectGoal, setProjectGoal] = useState("");
  const [creating, setCreating] = useState(false);

  const refresh = () => {
    setLoading(true);
    getDashboard().then(setData).catch((e) => setError(e.message)).finally(() => setLoading(false));
  };

  useEffect(() => { refresh(); }, []);

  const doRunScheduler = async () => {
    setActionMsg("Running scheduler...");
    try {
      const r = await runScheduler();
      setActionMsg(`Ran ${r.ran} jobs.`);
      refresh();
    } catch (e: any) {
      setActionMsg(`Error: ${e.message}`);
    }
  };

  if (loading) return <div className="text-zinc-500 p-8">Loading...</div>;
  if (error) return <div className="text-red-400 p-8">Failed: {error}. Is the API running?</div>;
  if (!data) return null;

  const budgetPct = data.budget ? Math.round((data.total_spend_30d / data.budget) * 100) : null;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">{data.org_name}</h1>
        <div className="flex gap-2">
          <button onClick={doRunScheduler} className="bg-blue-600 hover:bg-blue-500 text-white text-sm px-4 py-2 rounded-lg transition-colors">
            Run Scheduler
          </button>
          <button onClick={refresh} className="bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-sm px-4 py-2 rounded-lg transition-colors">
            Refresh
          </button>
        </div>
      </div>
      {actionMsg && <div className="bg-zinc-800 text-zinc-300 text-sm px-4 py-2 rounded-lg">{actionMsg}</div>}

      <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-4">
        <h2 className="text-sm font-semibold mb-2 text-zinc-400">New Project</h2>
        <div className="flex gap-2">
          <input
            type="text"
            value={projectGoal}
            onChange={(e) => setProjectGoal(e.target.value)}
            placeholder="e.g. Scan energy ETFs from Yahoo Finance and generate a risk report"
            className="flex-1 bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-300 focus:outline-none focus:border-zinc-500"
            onKeyDown={(e) => { if (e.key === "Enter") { setCreating(true); createProject(projectGoal).then(r => { setActionMsg(`Created: ${r.project_name} (${r.tasks} tasks)`); setProjectGoal(""); refresh(); setCreating(false); }).catch(e => { setActionMsg(`Error: ${e.message}`); setCreating(false); }); }}} />
          <button
            disabled={!projectGoal.trim() || creating}
            onClick={async () => {
              setCreating(true);
              try { const r = await createProject(projectGoal); setActionMsg(`Created: ${r.project_name} (${r.tasks} tasks)`); setProjectGoal(""); refresh(); }
              catch (e: any) { setActionMsg(`Error: ${e.message}`); }
              setCreating(false);
            }}
            className="bg-green-600 hover:bg-green-500 disabled:bg-zinc-700 disabled:text-zinc-500 text-white text-sm px-4 py-2 rounded-lg transition-colors shrink-0"
          >
            {creating ? "Creating..." : "Create Project"}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Stat label="Departments" value={data.departments.length} />
        <Stat label="30-Day Spend" value={data.total_spend_30d} unit="tokens" />
        <Stat label="30-Day Runs" value={data.total_runs_30d} />
        {budgetPct !== null && <Stat label="Budget Used" value={`${budgetPct}%`} />}
      </div>

      <div className="flex gap-2">
        <Link href="/calendar" className="text-sm text-blue-400 hover:text-blue-300">
          Calendar →
        </Link>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {data.departments.map((d) => (
          <div key={d.name} className="bg-zinc-900 border border-zinc-800 rounded-lg p-4">
            <div className="flex items-center justify-between mb-2">
              <h3 className="font-semibold">{d.name}</h3>
              <span className="text-xs text-zinc-500">{d.success_rate}% success · {d.recent_runs} runs</span>
            </div>
            <div className="flex gap-2 text-xs text-zinc-500">
              <span>{d.spend_7d.toLocaleString()} tokens / 7d</span>
              {d.failures > 0 && <span className="text-red-400">{d.failures} failures</span>}
            </div>
          </div>
        ))}
      </div>

      <div>
        <h2 className="text-lg font-semibold mb-3">Recent Activity</h2>
        <div className="space-y-2">
          {data.recent_activity.slice(0, 15).map((r) => (
            <div key={r.id} className="bg-zinc-900 border border-zinc-800 rounded-lg p-3 flex items-start gap-3">
              <StatusBadge status={r.status} />
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium">{r.department}/{r.role}</div>
                <div className="text-xs text-zinc-500 truncate">{r.summary}</div>
              </div>
              <div className="text-xs text-zinc-600 shrink-0">{r.tokens.toLocaleString()} tokens</div>
            </div>
          ))}
        </div>
      </div>

      {data.projects.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-lg font-semibold">Active Projects</h2>
            <Link href="/projects" className="text-sm text-blue-400 hover:text-blue-300">View all →</Link>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {data.projects.map((p) => (
              <div key={p.id} className="bg-zinc-900 border border-zinc-800 rounded-lg p-3">
                <div className="flex items-center justify-between">
                  <h3 className="font-medium text-sm">{p.name}</h3>
                  <StatusBadge status={p.status} />
                </div>
                <div className="text-xs text-zinc-500 mt-1 truncate">{p.goal}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

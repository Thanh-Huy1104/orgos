"use client";

import { useEffect, useState } from "react";
import { ProjectSummary, ProjectDetail, getProjects, getProject, dispatchProject } from "@/lib/api";

function StatusBadge({ status }: { status: string }) {
  const c: Record<string, string> = { active: "bg-blue-900/50 text-blue-400 border-blue-800", completed: "bg-green-900/50 text-green-400 border-green-800", blocked: "bg-yellow-900/50 text-yellow-400 border-yellow-800", in_progress: "bg-blue-900/50 text-blue-400 border-blue-800" };
  return <span className={`text-xs px-2 py-0.5 rounded border ${c[status] || "bg-zinc-800 text-zinc-400"}`}>{status}</span>;
}

export default function ProjectsPage() {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [selected, setSelected] = useState<ProjectDetail | null>(null);
  const [msg, setMsg] = useState("");

  const load = () => getProjects().then(setProjects);

  useEffect(() => { load(); }, []);

  const doDispatch = async (id: string) => {
    setMsg("Dispatching...");
    try {
      const r = await dispatchProject(id);
      setMsg(`Dispatched ${r.dispatched} tasks`);
      const p = await getProject(id);
      setSelected(p);
      load();
    } catch (e: any) { setMsg(`Error: ${e.message}`); }
  };

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Projects</h1>
      {msg && <div className="bg-zinc-800 text-zinc-300 text-sm px-4 py-2 rounded-lg">{msg}</div>}

      <div className="space-y-3">
        {projects.map((p) => (
          <div key={p.id} className="bg-zinc-900 border border-zinc-800 rounded-lg p-4 cursor-pointer hover:border-zinc-700"
            onClick={() => getProject(p.id).then(setSelected)}>
            <div className="flex items-center justify-between">
              <h3 className="font-medium">{p.name}</h3>
              <StatusBadge status={p.status} />
            </div>
            <p className="text-xs text-zinc-500 mt-1">{p.goal}</p>
            {p.task_count !== undefined && <p className="text-xs text-zinc-600 mt-2">{p.task_count} tasks</p>}
          </div>
        ))}
      </div>

      {selected && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={() => setSelected(null)}>
          <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-6 max-w-lg w-full mx-4 max-h-[80vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-2">
              <h2 className="text-xl font-bold">{selected.project_name}</h2>
              <StatusBadge status={selected.project_status} />
            </div>
            <p className="text-sm text-zinc-400 mb-3">{selected.goal}</p>

            <div className="grid grid-cols-3 gap-2 mb-3 text-center">
              <div className="bg-zinc-800 rounded p-2"><div className="text-lg font-bold text-green-400">{selected.tasks_done}</div><div className="text-xs text-zinc-500">Done</div></div>
              <div className="bg-zinc-800 rounded p-2"><div className="text-lg font-bold text-blue-400">{selected.tasks_in_progress}</div><div className="text-xs text-zinc-500">In Progress</div></div>
              <div className="bg-zinc-800 rounded p-2"><div className="text-lg font-bold text-zinc-400">{selected.tasks_todo}</div><div className="text-xs text-zinc-500">Todo</div></div>
            </div>

            <div className="w-full bg-zinc-800 rounded-full h-2 mb-4">
              <div className="bg-green-500 h-2 rounded-full transition-all" style={{ width: `${selected.progress_pct}%` }} />
            </div>

            <div className="space-y-2 mb-4">
              {selected.tasks.map((t) => (
                <div key={t.id} className="flex items-center justify-between text-sm bg-zinc-800 rounded p-2">
                  <span className="truncate flex-1">{t.title}</span>
                  <span className={`text-xs ml-2 px-2 py-0.5 rounded ${t.priority === "critical" ? "bg-red-900/50 text-red-400" : t.priority === "high" ? "bg-orange-900/50 text-orange-400" : "bg-zinc-700 text-zinc-400"}`}>{t.priority}</span>
                  <StatusBadge status={t.status} />
                </div>
              ))}
            </div>

            {selected.tasks_todo > 0 && (
              <button onClick={() => doDispatch(selected.project_id)} className="w-full bg-green-600 hover:bg-green-500 text-white text-sm py-2 rounded-lg transition-colors">
                Dispatch {selected.tasks_todo} Pending Tasks
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

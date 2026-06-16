"use client";

import { useEffect, useState } from "react";
import { ProjectSummary, ProjectDetail, getProjects, getProject, dispatchProject, getLogs, RunEntry } from "@/lib/api";

function Badge({ status, label }: { status: string; label?: string }) {
  const c: Record<string, string> = { completed: "badge-green", failed: "badge-red", blocked: "badge-yellow", active: "badge-blue", in_progress: "badge-blue", done: "badge-green", todo: "badge-gray", needs_revision: "badge-yellow" };
  return <span className={`badge ${c[status] || "badge-gray"}`}>{label || status}</span>;
}

export default function ProjectsPage() {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [selected, setSelected] = useState<ProjectDetail | null>(null);
  const [logs, setLogs] = useState<RunEntry[]>([]);
  const [msg, setMsg] = useState("");

  const load = () => getProjects().then(setProjects);

  useEffect(() => { load(); }, []);

  const openProject = async (id: string) => {
    const p = await getProject(id);
    setSelected(p);
    const all = await getLogs();
    setLogs(all.filter(l => p.tasks.some(t => t.title && l.summary?.includes(t.title.slice(0, 20)))));
  };

  const doDispatch = async (id: string) => {
    setMsg("Dispatching...");
    try { const r = await dispatchProject(id); setMsg(`Dispatched ${r.dispatched} tasks`); const p = await getProject(id); setSelected(p); load(); }
    catch (e: any) { setMsg(`Error: ${e.message}`); }
  };

  return (
    <div className="space-y-5">
      <h1 className="text-xl font-semibold">Projects</h1>
      {msg && <div className="text-sm p-3 rounded-lg" style={{ background: "var(--bg-secondary)", color: "var(--text-secondary)" }}>{msg}</div>}

      {projects.length === 0 ? (
        <div className="card text-sm" style={{ color: "var(--text-muted)" }}>No projects yet. Create one from the Dashboard.</div>
      ) : (
        <div className="space-y-2">
          {projects.map(p => (
            <div key={p.id} className="card cursor-pointer" onClick={() => openProject(p.id)}>
              <div className="flex justify-between items-center">
                <span className="font-medium text-sm">{p.name}</span>
                <Badge status={p.status} />
              </div>
              <div className="text-xs mt-1 truncate" style={{ color: "var(--text-muted)" }}>{p.goal}</div>
              {p.task_count !== undefined && <div className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>{p.task_count} tasks</div>}
            </div>
          ))}
        </div>
      )}

      {selected && (
        <div className="modal-overlay" onClick={() => setSelected(null)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <div className="flex justify-between items-start mb-3">
              <div>
                <h2 className="text-lg font-semibold">{selected.project_name}</h2>
                <Badge status={selected.project_status} />
              </div>
              <button className="text-lg leading-none" style={{ color: "var(--text-muted)" }} onClick={() => setSelected(null)}>×</button>
            </div>
            <p className="text-sm mb-3" style={{ color: "var(--text-secondary)" }}>{selected.goal}</p>

            <div className="grid grid-cols-3 gap-2 mb-3 text-center">
              <div className="p-2 rounded-lg" style={{ background: "var(--green-bg)" }}><div className="font-semibold" style={{ color: "var(--green)" }}>{selected.tasks_done}</div><div className="text-xs" style={{ color: "var(--green)" }}>Done</div></div>
              <div className="p-2 rounded-lg" style={{ background: "var(--blue-bg)" }}><div className="font-semibold" style={{ color: "var(--blue)" }}>{selected.tasks_in_progress}</div><div className="text-xs" style={{ color: "var(--blue)" }}>In Progress</div></div>
              <div className="p-2 rounded-lg" style={{ background: "var(--bg-secondary)" }}><div className="font-semibold" style={{ color: "var(--text-secondary)" }}>{selected.tasks_todo}</div><div className="text-xs" style={{ color: "var(--text-muted)" }}>Todo</div></div>
            </div>

            <div className="w-full h-1.5 rounded-full mb-4" style={{ background: "var(--bg-secondary)" }}>
              <div className="h-1.5 rounded-full transition-all" style={{ width: `${selected.progress_pct}%`, background: "var(--green)" }} />
            </div>

            <div className="space-y-1 mb-3 max-h-64 overflow-y-auto">
              {selected.tasks.map(t => (
                <div key={t.id} className="p-2 rounded-lg" style={{ background: t.status === "done" ? "var(--green-bg)" : "var(--bg-secondary)" }}>
                  <div className="flex justify-between items-center">
                    <span className="text-sm truncate flex-1">{t.title}</span>
                    <div className="flex gap-1 ml-2">
                      <Badge status={t.status} />
                    </div>
                  </div>
                  {t.description && t.status === "done" && (
                    <details className="mt-1">
                      <summary className="text-xs cursor-pointer" style={{ color: "var(--text-muted)" }}>View results</summary>
                      <pre className="text-xs mt-1 whitespace-pre-wrap max-h-32 overflow-y-auto p-2 rounded" style={{ background: "white", color: "var(--text-secondary)" }}>{t.description}</pre>
                    </details>
                  )}
                </div>
              ))}
            </div>

            {selected.tasks_todo > 0 && (
              <button className="btn btn-green w-full" onClick={() => doDispatch(selected.project_id)}>
                Dispatch {selected.tasks_todo} Pending Tasks
              </button>
            )}

            {selected.final_report && (
              <div className="mt-3 p-3 rounded-lg" style={{ background: "var(--blue-bg)" }}>
                <div className="text-xs font-semibold mb-1" style={{ color: "var(--blue)" }}>Final Report</div>
                <pre className="text-xs whitespace-pre-wrap max-h-40 overflow-y-auto" style={{ color: "var(--text-primary)" }}>{selected.final_report}</pre>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

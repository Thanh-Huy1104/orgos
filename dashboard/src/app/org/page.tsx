"use client";

import { useEffect, useState } from "react";

const API_BASE = "";

interface RoleInfo {
  name: string; tier: string; model: string; system_prompt: string;
  tools: string[]; mcps: string[]; skills: string[];
}

interface DeptMetrics {
  spend_7d: number; spend_30d: number; runs_7d: number;
  recent_runs: number; success_rate: number; failures: number;
  recent_runs_detail: { id: string; role: string; status: string; summary: string; tokens: number; created_at: string }[];
}

interface DeptInfo {
  name: string; description: string;
  supervisor: RoleInfo | null; members: RoleInfo[];
  sops: { name: string; cadence: string | null; objective: string }[];
  shared_mcps: string[];
  metrics: DeptMetrics;
}

function unique(arr: string[]) { return [...new Set(arr)]; }

const deptColor: Record<string, string> = {
  research: "#8B5CF6", engineering: "#F59E0B", operations: "#10B981",
  compliance: "#EF4444", quant: "#3B82F6",
};

const STATUS_COLOR: Record<string, string> = {
  completed: "var(--green)", failed: "var(--red)", running: "var(--yellow)",
};

export default function OrgPage() {
  const [depts, setDepts] = useState<DeptInfo[]>([]);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [selected, setSelected] = useState<RoleInfo | null>(null);

  useEffect(() => {
    fetch(`${API_BASE}/api/org`).then(r => r.json()).then(d => {
      setDepts(d.departments || []);
      const ex: Record<string, boolean> = {};
      (d.departments || []).forEach((dp: DeptInfo) => { ex[dp.name] = true; });
      setExpanded(ex);
    });
  }, []);

  const fmtTokens = (n: number) => n > 1000 ? `${(n / 1000).toFixed(1)}k` : String(n);

  return (
    <div className="flex" style={{ height: "calc(100vh - 88px)" }}>
      <div className={`space-y-6 overflow-y-auto ${selected ? 'w-1/2 pr-4' : 'max-w-2xl'}`}>
        <div>
          <h1 className="text-lg font-semibold mb-1">Organization</h1>
          <p className="text-sm" style={{ color: "var(--text-muted)" }}>
            Owned by you · Orchestrated by LLM · Executed by agents
          </p>
        </div>

        <div className="space-y-3 ml-5 pl-4 border-l-2" style={{ borderColor: "var(--border)" }}>
          {depts.map(d => (
            <div key={d.name}>
              <div
                className="flex items-center gap-2 cursor-pointer py-1"
                onClick={() => setExpanded(p => ({ ...p, [d.name]: !p[d.name] }))}
              >
                <div className="w-2 h-2 rounded-full" style={{ background: deptColor[d.name] || "var(--text-muted)" }} />
                <span className="text-sm font-medium">{d.name}</span>
                <span className="text-xs" style={{ color: "var(--text-muted)" }}>
                  {[d.supervisor, ...d.members].filter(Boolean).length} agents
                </span>
                {d.metrics && (
                  <span className="text-xs ml-auto flex items-center gap-3" style={{ color: "var(--text-muted)" }}>
                    <span style={{ color: d.metrics.success_rate >= 80 ? "var(--green)" : d.metrics.success_rate > 0 ? "var(--yellow)" : "var(--text-muted)" }}>
                      {d.metrics.success_rate}%
                    </span>
                    <span>{fmtTokens(d.metrics.spend_30d)} tok/30d</span>
                    <span>{d.metrics.runs_7d} runs/wk</span>
                  </span>
                )}
                <span className="text-xs" style={{ color: "var(--text-muted)" }}>{expanded[d.name] ? "▾" : "▸"}</span>
              </div>

              {expanded[d.name] && (
                <div className="ml-5 pl-4 border-l-2 mt-1 mb-3 space-y-1" style={{ borderColor: deptColor[d.name] + "30" }}>
                  {[d.supervisor, ...d.members].filter(Boolean).map((r, i) => (
                    <div key={(r as RoleInfo).name}
                      className="flex items-center gap-2 text-sm cursor-pointer py-0.5 hover:bg-[var(--bg-hover)] rounded px-1 -mx-1"
                      onClick={() => setSelected(selected?.name === (r as RoleInfo).name ? null : r as RoleInfo)}>
                      <span>{(r as RoleInfo).name}</span>
                      <span className="badge badge-gray" style={{ fontSize: 9 }}>{(r as RoleInfo).tier}</span>
                    </div>
                  ))}
                  {d.sops.length > 0 && (
                    <div className="text-xs pt-1" style={{ color: "var(--text-muted)" }}>
                      {d.sops.map(s => (
                        <div key={s.name} className="flex gap-2 py-0.5">
                          <span>{s.name}</span>
                          {s.cadence && <span className="badge badge-gray">{s.cadence}</span>}
                        </div>
                      ))}
                    </div>
                  )}
                  {d.metrics?.recent_runs_detail?.length > 0 && (
                    <div className="text-xs pt-2 space-y-1">
                      <div className="font-semibold" style={{ color: "var(--text-muted)" }}>Recent runs</div>
                      {d.metrics.recent_runs_detail.slice(0, 3).map(r => (
                        <div key={r.id} className="flex items-center gap-2">
                          <span style={{ color: STATUS_COLOR[r.status] || "var(--text-muted)" }}>●</span>
                          <span>{r.role}</span>
                          <span className="badge badge-gray">{r.status}</span>
                          <span style={{ color: "var(--text-muted)" }}>{fmtTokens(r.tokens)} tok</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Right sidebar detail */}
      {selected && (
        <div className="w-1/2 shrink-0 border-l pl-5 overflow-y-auto" style={{ borderColor: "var(--border)" }}>
          <div className="flex justify-between items-center mb-4">
            <div>
              <h2 className="font-semibold">{selected.name}</h2>
              <span className="badge badge-gray">{selected.tier}</span>
              <span className="text-xs ml-2" style={{ color: "var(--text-muted)" }}>{selected.model}</span>
            </div>
            <button className="text-lg" style={{ color: "var(--text-muted)" }} onClick={() => setSelected(null)}>×</button>
          </div>

          <div className="card mb-3">
            <div className="text-xs font-semibold mb-1" style={{ color: "var(--text-muted)" }}>System Prompt</div>
            <pre className="text-xs whitespace-pre-wrap" style={{ color: "var(--text-secondary)", maxHeight: 256, overflowY: "auto" }}>
              {selected.system_prompt}
            </pre>
          </div>

          <div className="card mb-3">
            <div className="text-xs font-semibold mb-1" style={{ color: "var(--text-muted)" }}>
              Tools ({unique(selected.tools).length})
            </div>
            <div className="flex flex-wrap gap-1">
              {unique(selected.tools).map(t => <span key={t} className="badge badge-green">{t}</span>)}
              {selected.tools.length === 0 && <span className="text-xs" style={{ color: "var(--text-muted)" }}>none</span>}
            </div>
          </div>

          <div className="card">
            <div className="text-xs font-semibold mb-1" style={{ color: "var(--text-muted)" }}>
              MCPs ({unique(selected.mcps).length})
            </div>
            <div className="flex flex-wrap gap-1">
              {unique(selected.mcps).map(m => <span key={m} className="badge badge-blue">{m.replace(/.*python3/m, 'python')}</span>)}
              {selected.mcps.length === 0 && <span className="text-xs" style={{ color: "var(--text-muted)" }}>none</span>}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

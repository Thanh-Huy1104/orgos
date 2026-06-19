"use client";

import { useEffect, useState } from "react";

const API_BASE = "";

interface RoleInfo {
  name: string; tier: string; model: string; system_prompt: string;
  tools: string[]; mcps: string[]; skills: string[];
}

interface DeptInfo {
  name: string; description: string;
  supervisor: RoleInfo | null; members: RoleInfo[];
  sops: { name: string; cadence: string | null; objective: string }[];
  shared_mcps: string[];
  metrics: { spend_7d: number; spend_30d: number; runs_7d: number; success_rate: number; failures: number };
}

const deptColor: Record<string, string> = {
  research: "#8B5CF6", engineering: "#F59E0B", operations: "#10B981",
  compliance: "#EF4444", quant: "#3B82F6", assistant: "#6366F1",
  legal: "#D97706",
};

function unique(arr: string[]) { return [...new Set(arr)]; }

export default function OrgPage() {
  const [depts, setDepts] = useState<DeptInfo[]>([]);
  const [selected, setSelected] = useState<DeptInfo | null>(null);

  useEffect(() => {
    fetch(`${API_BASE}/api/org`).then(r => r.json()).then(d => setDepts(d.departments || []));
  }, []);

  const totalAgents = depts.reduce((n, d) => n + [d.supervisor, ...d.members].filter(Boolean).length, 0);

  return (
    <div className="org-layout">
      {/* Tree view */}
      <div className={`org-tree-panel ${selected ? "org-tree-narrow" : ""}`}>
        <h1 className="text-lg font-semibold mb-1">Organization</h1>
        <p className="text-xs mb-4" style={{ color: "var(--text-muted)" }}>
          {depts.length} departments · {totalAgents} agents
        </p>

        {/* Orchestrator root */}
        <div className="org-tree">
          <div className="org-node org-orchestrator" style={{ borderColor: "var(--accent)" }}>
            <span className="org-node-dot" style={{ background: "var(--accent)" }} />
            <span className="org-node-label">Orchestrator</span>
          </div>

          {/* Animated dotted connector lines */}
          <div className="org-connector">
            <svg className="org-svg-lines" viewBox="0 0 100 100" preserveAspectRatio="none">
              {depts.map((_, i) => {
                const n = depts.length;
                const x = 50;
                const y1 = 15;
                const y2 = 85;
                if (n === 1) {
                  return <line key={i} x1={x} y1={y1} x2={x} y2={y2} stroke="var(--border)" strokeWidth="1.5" strokeDasharray="5 5" className="org-dash-line" />;
                }
                const cx = 10 + (80 / (n - 1)) * i;
                return (
                  <g key={i}>
                    <line x1="50" y1={y1} x2={cx} y2={40} stroke="var(--border)" strokeWidth="1.5" strokeDasharray="5 5" className="org-dash-line" />
                    <line x1={cx} y1={40} x2={cx} y2={y2} stroke="var(--border)" strokeWidth="1.5" strokeDasharray="5 5" className="org-dash-line" />
                  </g>
                );
              })}
            </svg>
          </div>

          {/* Department nodes */}
          <div className="org-departments">
            {depts.map(d => {
              const color = deptColor[d.name] || "var(--text-muted)";
              const agentCount = [d.supervisor, ...d.members].filter(Boolean).length;
              const m = d.metrics;
              return (
                <button
                  key={d.name}
                  className={`org-dept-card ${selected?.name === d.name ? "selected" : ""}`}
                  onClick={() => setSelected(selected?.name === d.name ? null : d)}
                >
                  <div className="org-dept-header">
                    <span className="org-dot" style={{ background: color }} />
                    <span className="org-dept-name">{d.name}</span>
                    <span className="org-dept-count">{agentCount} agent{agentCount === 1 ? "" : "s"}</span>
                  </div>
                  <div className="org-dept-desc">{d.description}</div>
                  {m && (
                    <div className="org-dept-stats">
                      <span style={{ color: m.success_rate >= 80 ? "var(--green)" : m.success_rate > 0 ? "var(--yellow)" : "var(--text-muted)" }}>
                        {m.success_rate}% success
                      </span>
                      <span className="org-stat-sep">·</span>
                      <span>{m.runs_7d} runs/wk</span>
                      <span className="org-stat-sep">·</span>
                      <span>{(m.spend_30d / 1000).toFixed(0)}k tok/30d</span>
                    </div>
                  )}
                </button>
              );
            })}
          </div>
        </div>
      </div>

      {/* Detail panel */}
      {selected && (
        <div className="org-detail-panel">
          <div className="org-detail-header">
            <div>
              <div className="flex items-center gap-2 mb-1">
                <span className="org-dot" style={{ background: deptColor[selected.name] || "var(--text-muted)", width: 10, height: 10 }} />
                <h2 className="font-semibold text-base">{selected.name}</h2>
                <span className="badge badge-gray">{selected.metrics?.success_rate ?? "—"}%</span>
              </div>
              <div className="text-xs" style={{ color: "var(--text-muted)" }}>{selected.description}</div>
            </div>
            <button className="org-detail-close" onClick={() => setSelected(null)}>✕</button>
          </div>

          {/* Agents */}
          <div className="org-detail-section">
            <div className="text-xs font-semibold mb-2" style={{ color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.04em" }}>
              Agents
            </div>
            <div className="flex flex-col gap-2">
              {[selected.supervisor, ...selected.members].filter(Boolean).map(r => (
                <div key={(r as RoleInfo).name} className="card" style={{ padding: "10px 14px" }}>
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-sm font-medium">{(r as RoleInfo).name}</span>
                    <span className="badge badge-gray" style={{ fontSize: 9 }}>{(r as RoleInfo).tier}</span>
                    <span className="text-xs ml-auto" style={{ color: "var(--text-muted)" }}>{(r as RoleInfo).model}</span>
                  </div>
                  <div className="text-xs" style={{ color: "var(--text-muted)", lineHeight: 1.5 }}>
                    {(r as RoleInfo).system_prompt.slice(0, 200)}
                    {((r as RoleInfo).system_prompt.length > 200) ? "…" : ""}
                  </div>
                  <div className="flex flex-wrap gap-1 mt-2">
                    {unique((r as RoleInfo).tools).map(t => <span key={t} className="badge badge-green" style={{ fontSize: 10 }}>{t}</span>)}
                    {unique((r as RoleInfo).mcps).map(m => <span key={m} className="badge badge-blue" style={{ fontSize: 10 }}>{m}</span>)}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* SOPs */}
          {selected.sops.length > 0 && (
            <div className="org-detail-section">
              <div className="text-xs font-semibold mb-2" style={{ color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.04em" }}>
                Standard Operating Procedures
              </div>
              <div className="flex flex-col gap-1.5">
                {selected.sops.map(s => (
                  <div key={s.name} className="card" style={{ padding: "8px 12px" }}>
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium">{s.name}</span>
                      {s.cadence && <span className="badge badge-gray">{s.cadence}</span>}
                    </div>
                    <div className="text-xs mt-0.5" style={{ color: "var(--text-muted)" }}>{s.objective}</div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Stats */}
          {selected.metrics && (
            <div className="org-detail-section">
              <div className="text-xs font-semibold mb-2" style={{ color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.04em" }}>
                Usage
              </div>
              <div className="flex gap-3">
                <div className="card flex-1 text-center" style={{ padding: "10px" }}>
                  <div className="text-lg font-semibold" style={{ color: "var(--text-primary)" }}>{(selected.metrics.spend_30d / 1000).toFixed(1)}k</div>
                  <div className="text-xs" style={{ color: "var(--text-muted)" }}>tokens / 30d</div>
                </div>
                <div className="card flex-1 text-center" style={{ padding: "10px" }}>
                  <div className="text-lg font-semibold" style={{ color: "var(--text-primary)" }}>{selected.metrics.runs_7d}</div>
                  <div className="text-xs" style={{ color: "var(--text-muted)" }}>runs / week</div>
                </div>
                <div className="card flex-1 text-center" style={{ padding: "10px" }}>
                  <div className="text-lg font-semibold" style={{ color: selected.metrics.success_rate >= 80 ? "var(--green)" : "var(--yellow)" }}>{selected.metrics.success_rate}%</div>
                  <div className="text-xs" style={{ color: "var(--text-muted)" }}>success rate</div>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

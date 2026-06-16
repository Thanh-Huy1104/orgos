"use client";

import { useEffect, useState } from "react";

const API = "http://192.168.5.197:8420";
const ALL_CATS = ["privacy", "finance", "legal", "ethics", "security", "communications", "governance"];

export default function PoliciesPage() {
  const [policies, setPolicies] = useState<any[]>([]);
  const [cats, setCats] = useState<string[]>([]);
  const [filter, setFilter] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [pf, setPf] = useState({ id: "", title: "", cats: [] as string[], severity: "medium", rule: "", refs: "" });
  const [msg, setMsg] = useState("");

  const load = () => {
    fetch(`${API}/api/policies${filter ? `?category=${filter}` : ""}`)
      .then(r => r.json()).then(d => { setPolicies(d.policies || []); setCats(d.categories || []); });
  };
  useEffect(() => { load(); }, [filter]);

  const save = async () => {
    if (!pf.id || !pf.title || !pf.rule) return;
    try {
      const r = await fetch(`${API}/api/policies`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...pf, categories: pf.cats, references: pf.refs.split("\n").filter(Boolean) }),
      });
      if (!r.ok) throw new Error((await r.json()).detail || "error");
      setMsg(`Policy ${pf.id} added.`); setShowForm(false);
      setPf({ id: "", title: "", cats: [], severity: "medium", rule: "", refs: "" }); load();
    } catch (e: any) { setMsg(`${e.message}`); }
  };

  const del = async (id: string) => {
    await fetch(`${API}/api/policies/${id}`, { method: "DELETE" }); load();
  };

  const toggleCat = (c: string) => {
    setPf(p => ({ ...p, cats: p.cats.includes(c) ? p.cats.filter(x => x !== c) : [...p.cats, c] }));
  };

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Policies</h1>
        <div className="flex gap-2">
          <select className="input text-sm" value={filter} onChange={e => setFilter(e.target.value)}>
            <option value="">All categories</option>
            {cats.map(c => <option key={c}>{c}</option>)}
          </select>
          <button className="btn btn-primary text-sm" onClick={() => setShowForm(!showForm)}>
            {showForm ? "Cancel" : "Add Policy"}
          </button>
        </div>
      </div>
      {msg && <div className="text-sm p-3 rounded-lg" style={{ background: "var(--bg-secondary)", color: "var(--text-secondary)" }}>{msg}</div>}

      {showForm && (
        <div className="card space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <input className="input" placeholder="ID (e.g. POL-011)" value={pf.id} onChange={e => setPf({ ...pf, id: e.target.value })} />
            <select className="input" value={pf.severity} onChange={e => setPf({ ...pf, severity: e.target.value })}>
              {["low", "medium", "high", "critical"].map(s => <option key={s}>{s}</option>)}
            </select>
          </div>
          <div className="flex flex-wrap gap-1">
            {ALL_CATS.map(c => (
              <button key={c} className={`text-xs px-2 py-1 rounded border ${pf.cats.includes(c) ? "badge badge-blue" : "badge badge-gray"}`}
                onClick={() => toggleCat(c)}>{c}</button>
            ))}
          </div>
          <input className="input w-full" placeholder="Title" value={pf.title} onChange={e => setPf({ ...pf, title: e.target.value })} />
          <textarea className="input w-full" rows={4} placeholder="Rule text..." value={pf.rule} onChange={e => setPf({ ...pf, rule: e.target.value })} />
          <textarea className="input w-full" rows={2} placeholder="References (one per line)" value={pf.refs} onChange={e => setPf({ ...pf, refs: e.target.value })} />
          <button className="btn btn-green" onClick={save}>Save Policy</button>
        </div>
      )}

      <div className="space-y-2">
        {policies.map((p: any) => (
          <div key={p.id} className="card">
            <div className="flex items-start justify-between">
              <div className="flex-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-sm font-medium">{p.id}: {p.title}</span>
                  {(p.categories || [p.category]).map((c: string) => (
                    <span key={c} className="badge badge-blue">{c}</span>
                  ))}
                  <span className={`badge ${p.severity === "critical" ? "badge-red" : p.severity === "high" ? "badge-yellow" : "badge-gray"}`}>{p.severity}</span>
                </div>
                <div className="text-xs mt-1" style={{ color: "var(--text-secondary)" }}>{p.rule?.slice(0, 250)}</div>
                {p.references?.length > 0 && (
                  <div className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
                    Refs: {(p.references || []).slice(0, 3).join(", ")}
                  </div>
                )}
              </div>
              <button className="text-xs ml-2" style={{ color: "var(--red)" }} onClick={() => del(p.id)}>×</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

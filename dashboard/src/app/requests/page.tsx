"use client";

import { useEffect, useState } from "react";
import { getProposals, CredentialRequest, ToolRequest, resolveCredential } from "@/lib/api";

export default function RequestsPage() {
  const [creds, setCreds] = useState<CredentialRequest[]>([]);
  const [tools, setTools] = useState<ToolRequest[]>([]);
  const [msg, setMsg] = useState("");

  const load = () => getProposals().then(d => { setCreds(d.credential_requests); setTools(d.tool_requests); });
  useEffect(() => { load(); }, []);

  const doResolve = async (i: number) => {
    try { const r = await resolveCredential(i); setMsg(`Resolved. ${r.remaining} remaining.`); load(); }
    catch (e: any) { setMsg(`${e.message}`); }
  };

  return (
    <div className="space-y-5">
      <h1 className="text-xl font-semibold">Requests</h1>
      {msg && <div className="text-sm p-3 rounded-lg" style={{ background: "var(--bg-secondary)" }}>{msg}</div>}
      {creds.length === 0 && tools.length === 0 && (
        <div className="card text-sm" style={{ color: "var(--text-muted)" }}>No pending requests. The org will ask for credentials and tools when needed.</div>
      )}
      {creds.map((c, i) => (
        <div key={i} className="card" style={{ borderColor: "var(--yellow)" }}>
          <div className="flex justify-between items-center">
            <span className="text-sm font-medium" style={{ color: "var(--yellow)" }}>{c.department} — Credential Request</span>
            <button className="btn btn-green text-xs" onClick={() => doResolve(i)}>Resolved</button>
          </div>
          {c.credential_needs.map((n, j) => (
            <div key={j} className="text-sm p-2 rounded mt-1" style={{ background: "var(--bg-secondary)" }}>
              <span className="font-mono" style={{ color: "var(--blue)" }}>{n.name}</span>
              <span className="ml-2" style={{ color: "var(--text-secondary)" }}>— {n.purpose}</span>
              {n.url && <div className="text-xs mt-0.5" style={{ color: "var(--text-muted)" }}>{n.url}</div>}
            </div>
          ))}
        </div>
      ))}
      {tools.map((t, i) => (
        <div key={i} className="card" style={{ borderColor: "var(--blue)" }}>
          <span className="text-sm font-medium" style={{ color: "var(--blue)" }}>{t.department} — Tool Request</span>
          <div className="flex gap-1 mt-2">{t.recommended_tools.map(tool => <span key={tool} className="badge badge-blue">{tool}</span>)}</div>
        </div>
      ))}
    </div>
  );
}

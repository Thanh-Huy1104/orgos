"use client";

import { useEffect, useState } from "react";
import { getProposals, CredentialRequest, ToolRequest, resolveCredential } from "@/lib/api";

export default function ProposalsPage() {
  const [creds, setCreds] = useState<CredentialRequest[]>([]);
  const [tools, setTools] = useState<ToolRequest[]>([]);
  const [policies, setPolicies] = useState<unknown[]>([]);
  const [msg, setMsg] = useState("");

  const load = () => getProposals().then((d) => {
    setCreds(d.credential_requests); setTools(d.tool_requests); setPolicies(d.policy_changes);
  });

  useEffect(() => { load(); }, []);

  const doResolve = async (index: number) => {
    try { const r = await resolveCredential(index); setMsg(`Resolved ${r.resolved}. ${r.remaining} remaining.`); load(); }
    catch (e: any) { setMsg(`Error: ${e.message}`); }
  };

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Proposals & Requests</h1>
      {msg && <div className="bg-zinc-800 text-zinc-300 text-sm px-4 py-2 rounded-lg">{msg}</div>}

      {creds.length > 0 && (
        <section>
          <h2 className="text-lg font-semibold mb-3 text-yellow-400">Credential Requests ({creds.length})</h2>
          <div className="space-y-3">
            {creds.map((c, i) => (
              <div key={i} className="bg-zinc-900 border border-yellow-900 rounded-lg p-4">
                <div className="flex items-center justify-between">
                  <div className="text-sm font-medium text-yellow-300">{c.department}</div>
                  <button onClick={() => doResolve(i)} className="text-xs bg-green-700 hover:bg-green-600 text-white px-3 py-1 rounded transition-colors">
                    Mark Resolved
                  </button>
                </div>
                <div className="mt-2 space-y-1">
                  {c.credential_needs.map((n, j) => (
                    <div key={j} className="bg-zinc-800 rounded p-2 text-sm">
                      <span className="font-mono text-blue-400">{n.name}</span>
                      <span className="text-zinc-500 ml-2">— {n.purpose}</span>
                      {n.url && <div className="text-xs text-zinc-600 mt-1">Get it at: {n.url}</div>}
                    </div>
                  ))}
                </div>
                <p className="text-xs text-zinc-600 mt-2">{c.reasoning?.slice(0, 200)}</p>
              </div>
            ))}
          </div>
        </section>
      )}

      {tools.length > 0 && (
        <section>
          <h2 className="text-lg font-semibold mb-3 text-blue-400">Tool Requests ({tools.length})</h2>
          <div className="space-y-3">
            {tools.map((t, i) => (
              <div key={i} className="bg-zinc-900 border border-blue-900 rounded-lg p-4">
                <div className="text-sm font-medium text-blue-300">{t.department}</div>
                <div className="flex flex-wrap gap-2 mt-2">
                  {t.recommended_tools.map((tool) => (
                    <span key={tool} className="text-xs bg-blue-900/30 text-blue-300 px-2 py-0.5 rounded border border-blue-800">{tool}</span>
                  ))}
                </div>
                {t.recommended_mcps.length > 0 && (
                  <div className="flex flex-wrap gap-2 mt-1">
                    {t.recommended_mcps.map((m) => (
                      <span key={m} className="text-xs bg-zinc-800 text-zinc-400 px-2 py-0.5 rounded">{m}</span>
                    ))}
                  </div>
                )}
                <p className="text-xs text-zinc-600 mt-2">{t.reasoning?.slice(0, 200)}</p>
              </div>
            ))}
          </div>
        </section>
      )}

      {policies.length > 0 && (
        <section>
          <h2 className="text-lg font-semibold mb-3 text-purple-400">Policy Changes ({policies.length})</h2>
          {policies.map((p: any, i) => (
            <div key={i} className="bg-zinc-900 border border-zinc-800 rounded-lg p-3">
              <pre className="text-xs text-zinc-400 whitespace-pre-wrap">{JSON.stringify(p, null, 2)}</pre>
            </div>
          ))}
        </section>
      )}

      {creds.length === 0 && tools.length === 0 && policies.length === 0 && (
        <p className="text-zinc-500">No pending requests. The org hasn't requested any changes yet.</p>
      )}
    </div>
  );
}

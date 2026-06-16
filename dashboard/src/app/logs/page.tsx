"use client";

import { useEffect, useState } from "react";
import { RunEntry, getLogs } from "@/lib/api";

function Badge({ status }: { status: string }) {
  const c: Record<string, string> = { completed: "badge-green", failed: "badge-red", blocked: "badge-yellow", needs_revision: "badge-yellow" };
  return <span className={`badge ${c[status] || "badge-gray"}`}>{status}</span>;
}

export default function LogsPage() {
  const [logs, setLogs] = useState<RunEntry[]>([]);
  const [dept, setDept] = useState("");

  useEffect(() => { getLogs(dept || undefined).then(setLogs); }, [dept]);

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h1 className="text-xl font-semibold">Logs</h1>
        <select className="input text-sm" value={dept} onChange={e => setDept(e.target.value)}>
          <option value="">All departments</option>
          <option value="assistant">Assistant</option>
          <option value="finance">Finance</option>
          <option value="legal">Legal</option>
        </select>
      </div>

      {logs.length === 0 ? (
        <div className="card text-sm" style={{ color: "var(--text-muted)" }}>No runs yet.</div>
      ) : (
        <div className="space-y-1">
          {logs.map(r => (
            <div key={r.id} className="card flex items-start gap-3" style={{ padding: "10px 14px" }}>
              <Badge status={r.status} />
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium">{r.department}/{r.role}</div>
                <div className="text-xs mt-0.5" style={{ color: "var(--text-secondary)" }}>{r.summary}</div>
                <div className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
                  {r.tokens?.toLocaleString() ?? 0} tokens · {new Date(r.created_at).toLocaleString()}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

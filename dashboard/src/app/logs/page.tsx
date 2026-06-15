"use client";

import { useEffect, useState } from "react";
import { RunEntry, getLogs } from "@/lib/api";

export default function LogsPage() {
  const [logs, setLogs] = useState<RunEntry[]>([]);
  const [filter, setFilter] = useState("");

  useEffect(() => {
    getLogs(filter || undefined).then(setLogs);
  }, [filter]);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Logs</h1>
        <input
          type="text"
          placeholder="Filter by department..."
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="bg-zinc-900 border border-zinc-700 rounded px-3 py-1.5 text-sm text-zinc-300 focus:outline-none focus:border-zinc-500 w-48"
        />
      </div>
      <div className="space-y-1">
        {logs.map((r) => (
          <div key={r.id} className="bg-zinc-900 border border-zinc-800 rounded-lg p-3 hover:border-zinc-700 transition-colors">
            <div className="flex items-center justify-between text-sm">
              <div>
                <span className="font-medium text-zinc-300">{r.department}/{r.role}</span>
                <span className={`ml-2 text-xs px-1.5 py-0.5 rounded ${r.status === "completed" ? "bg-green-900/50 text-green-400" : r.status === "failed" ? "bg-red-900/50 text-red-400" : "bg-zinc-800 text-zinc-500"}`}>{r.status}</span>
              </div>
              <span className="text-xs text-zinc-600">{new Date(r.created_at).toLocaleString()}</span>
            </div>
            <p className="text-xs text-zinc-500 mt-1 line-clamp-2">{r.summary}</p>
            <div className="text-xs text-zinc-600 mt-1">{(r.tokens ?? 0).toLocaleString()} tokens</div>
          </div>
        ))}
      </div>
    </div>
  );
}

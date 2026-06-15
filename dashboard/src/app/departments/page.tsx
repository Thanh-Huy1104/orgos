"use client";

import { useEffect, useState } from "react";
import { DepartmentMetric, RunEntry, getDepartments, getDepartmentRuns } from "@/lib/api";

export default function DepartmentsPage() {
  const [depts, setDepts] = useState<DepartmentMetric[]>([]);
  const [runs, setRuns] = useState<RunEntry[]>([]);
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => { getDepartments().then(setDepts); }, []);
  useEffect(() => {
    if (selected) getDepartmentRuns(selected).then(setRuns);
  }, [selected]);

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Departments</h1>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {depts.map((d) => (
          <div key={d.name} className={`bg-zinc-900 border rounded-lg p-4 cursor-pointer transition-colors ${selected === d.name ? "border-blue-500" : "border-zinc-800 hover:border-zinc-700"}`}
            onClick={() => setSelected(selected === d.name ? null : d.name)}>
            <h3 className="font-semibold">{d.name}</h3>
            <div className="grid grid-cols-3 gap-2 mt-2 text-xs text-zinc-500">
              <div><span className="text-zinc-300 font-medium">{d.spend_7d.toLocaleString()}</span> tokens/7d</div>
              <div><span className="text-zinc-300 font-medium">{d.success_rate}%</span> success</div>
              <div className={d.failures > 0 ? "text-red-400" : ""}>{d.failures} failures</div>
            </div>
          </div>
        ))}
      </div>
      {selected && runs.length > 0 && (
        <div>
          <h2 className="text-lg font-semibold mb-3">{selected} — Recent Runs</h2>
          <div className="space-y-2">
            {runs.slice(0, 30).map((r) => (
              <div key={r.id} className="bg-zinc-900 border border-zinc-800 rounded-lg p-3 text-sm">
                <div className="flex items-center justify-between">
                  <span className="font-medium">{r.role}</span>
                  <span className={`text-xs px-2 py-0.5 rounded border ${r.status === "completed" ? "bg-green-900/50 text-green-400 border-green-800" : "bg-red-900/50 text-red-400 border-red-800"}`}>{r.status}</span>
                </div>
                <p className="text-xs text-zinc-500 mt-1 truncate">{r.summary}</p>
                <div className="text-xs text-zinc-600 mt-1">{(r.tokens ?? 0).toLocaleString()} tokens · {new Date(r.created_at).toLocaleDateString()}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

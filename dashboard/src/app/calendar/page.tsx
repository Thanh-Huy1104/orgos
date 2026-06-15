"use client";

import { useEffect, useState } from "react";
import { CalendarJob, getCalendar, runScheduler, runDepartment } from "@/lib/api";

export default function CalendarPage() {
  const [jobs, setJobs] = useState<CalendarJob[]>([]);
  const [msg, setMsg] = useState("");

  const load = () => getCalendar().then((d) => setJobs(d.jobs));

  useEffect(() => { load(); }, []);

  const doRunAll = async () => {
    setMsg("Running...");
    try { const r = await runScheduler(); setMsg(`Ran ${r.ran} jobs`); load(); }
    catch (e: any) { setMsg(`Error: ${e.message}`); }
  };

  const doRunDept = async (name: string) => {
    setMsg(`Running ${name}...`);
    try { const r = await runDepartment(name); setMsg(`${name}: ${r.status}`); load(); }
    catch (e: any) { setMsg(`Error: ${e.message}`); }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Calendar</h1>
        <button onClick={doRunAll} className="bg-blue-600 hover:bg-blue-500 text-white text-sm px-4 py-2 rounded-lg transition-colors">
          Run All Pending
        </button>
      </div>
      {msg && <div className="bg-zinc-800 text-zinc-300 text-sm px-4 py-2 rounded-lg">{msg}</div>}

      <div className="space-y-3">
        {jobs.map((j) => (
          <div key={`${j.department}/${j.sop}`} className="bg-zinc-900 border border-zinc-800 rounded-lg p-4">
            <div className="flex items-center justify-between">
              <div>
                <span className="font-medium">{j.department}</span>
                <span className="text-zinc-500 mx-2">/</span>
                <span className="text-zinc-300">{j.sop}</span>
                <span className="ml-2 text-xs px-2 py-0.5 rounded bg-zinc-800 text-zinc-400">{j.cadence}</span>
              </div>
              <button onClick={() => doRunDept(j.department)} className="text-xs bg-zinc-800 hover:bg-zinc-700 text-zinc-300 px-3 py-1.5 rounded transition-colors">
                Run Now
              </button>
            </div>

            <div className="mt-2 text-xs text-zinc-500">
              Last run: {j.last_run ? new Date(j.last_run).toLocaleString() : "never"}
            </div>

            {j.recent_runs.length > 0 && (
              <div className="flex gap-2 mt-2">
                {j.recent_runs.map((r, i) => (
                  <span key={i} className={`text-xs px-2 py-0.5 rounded border ${
                    r.status === "completed" ? "bg-green-900/30 text-green-400 border-green-800" :
                    r.status === "failed" ? "bg-red-900/30 text-red-400 border-red-800" :
                    "bg-zinc-800 text-zinc-500 border-zinc-700"
                  }`}>
                    {r.status} ({r.tokens.toLocaleString()}t)
                  </span>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

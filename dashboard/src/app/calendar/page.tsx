"use client";

import { useEffect, useState } from "react";
import { getScheduler, SchedulerJob, CalendarJob, getCalendar } from "@/lib/api";

const API = "http://192.168.5.197:8420";

export default function CalendarPage() {
  const [jobs, setJobs] = useState<CalendarJob[]>([]);
  const [viewDate, setViewDate] = useState(new Date());
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`${API}/api/calendar`).then(r => r.json()).then(d => { setJobs(d.jobs || []); setLoading(false); });
  }, []);

  const month = viewDate.toLocaleString("default", { month: "long", year: "numeric" });
  const year = viewDate.getFullYear();
  const mon = viewDate.getMonth();
  const firstDay = new Date(year, mon, 1).getDay();
  const daysInMonth = new Date(year, mon + 1, 0).getDate();

  const prev = () => setViewDate(new Date(year, mon - 1, 1));
  const next = () => setViewDate(new Date(year, mon + 1, 1));

  // Build job map: day → list of job names
  const jobDays: Record<number, { dept: string; sop: string; cadence: string; lastRun: string | null }[]> = {};
  jobs.forEach(j => {
    if (j.cadence === "daily") {
      for (let d = 1; d <= daysInMonth; d++) jobDays[d] = [...(jobDays[d] || []), { dept: j.department, sop: j.sop, cadence: j.cadence, lastRun: j.last_run }];
    } else if (j.cadence === "weekly") {
      for (let d = 1; d <= daysInMonth; d++) {
        const dow = new Date(year, mon, d).getDay();
        if (dow === 1) jobDays[d] = [...(jobDays[d] || []), { dept: j.department, sop: j.sop, cadence: j.cadence, lastRun: j.last_run }];
      }
    }
  });

  const today = new Date();
  const isToday = (d: number) => today.getFullYear() === year && today.getMonth() === mon && today.getDate() === d;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Calendar</h1>
        <div className="flex items-center gap-3">
          <button className="btn btn-secondary text-xs" onClick={prev}>←</button>
          <span className="text-sm font-medium" style={{ minWidth: 140, textAlign: "center" }}>{month}</span>
          <button className="btn btn-secondary text-xs" onClick={next}>→</button>
          <button className="btn btn-secondary text-xs" onClick={() => setViewDate(new Date())}>Today</button>
        </div>
      </div>

      {/* Day headers */}
      <div className="grid grid-cols-7 text-center text-xs font-medium" style={{ color: "var(--text-muted)" }}>
        {["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map(d => <div key={d} className="py-1">{d}</div>)}
      </div>

      {/* Calendar grid */}
      <div className="grid grid-cols-7 border-l border-t rounded-lg overflow-hidden" style={{ borderColor: "var(--border)" }}>
        {/* Empty cells before first day */}
        {Array.from({ length: firstDay }).map((_, i) => (
          <div key={`empty-${i}`} className="border-r border-b p-2 min-h-[80px]" style={{ borderColor: "var(--border)", background: "var(--bg-secondary)" }} />
        ))}

        {/* Days */}
        {Array.from({ length: daysInMonth }).map((_, i) => {
          const day = i + 1;
          const dayJobs = jobDays[day] || [];
          const todayClass = isToday(day) ? { background: "var(--accent-light)", fontWeight: 600 } : {};

          return (
            <div key={day} className="border-r border-b p-1.5 min-h-[80px] text-xs" style={{ borderColor: "var(--border)", ...todayClass }}>
              <div className="mb-1">{day}</div>
              <div className="space-y-0.5">
                {dayJobs.slice(0, 3).map((j, ji) => (
                  <div key={ji} className="truncate rounded px-1 py-0.5 text-[10px]" style={{ background: deptBg(j.dept), color: deptFg(j.dept) }}>
                    {j.sop}
                  </div>
                ))}
                {dayJobs.length > 3 && (
                  <div className="text-[10px]" style={{ color: "var(--text-muted)" }}>+{dayJobs.length - 3} more</div>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Job list below calendar */}
      <div className="space-y-2">
        <h2 className="text-sm font-medium" style={{ color: "var(--text-secondary)" }}>Scheduled Jobs</h2>
        {jobs.map(j => (
          <div key={`${j.department}/${j.sop}`} className="card flex items-center justify-between" style={{ padding: "10px 14px" }}>
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 rounded-full" style={{ background: deptFg(j.department) }} />
              <span className="text-sm font-medium">{j.department}</span>
              <span className="text-sm" style={{ color: "var(--text-muted)" }}>/ {j.sop}</span>
              <span className="badge badge-gray">{j.cadence}</span>
            </div>
            <div className="flex items-center gap-3">
              <div className="text-xs" style={{ color: "var(--text-muted)" }}>
                Last: {j.last_run ? new Date(j.last_run).toLocaleDateString() : "never"}
              </div>
              {j.recent_runs?.slice(0, 3).map((r, i) => (
                <span key={i} className={`badge ${r.status === "completed" ? "badge-green" : "badge-red"}`}>
                  {r.tokens.toLocaleString()}t
                </span>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function deptBg(name: string) {
  return name === "assistant" ? "#EFF6FF" : name === "legal" ? "#FFFBEB" : "#ECFDF5";
}
function deptFg(name: string) {
  return name === "assistant" ? "#3B82F6" : name === "legal" ? "#D97706" : "#059669";
}

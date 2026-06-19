"use client";

import { useEffect, useState } from "react";
import { getCalendar, CalendarJob } from "@/lib/api";

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

const deptBg: Record<string, string> = {};
const deptFg: Record<string, string> = {};
function getDeptColor(name: string) {
  if (deptFg[name]) return { bg: deptBg[name], fg: deptFg[name] };
  const colors = ["#3B82F6", "#8B5CF6", "#10B981", "#F59E0B", "#EF4444", "#EC4899", "#6366F1"];
  const i = Object.keys(deptFg).length;
  const c = colors[i % colors.length];
  deptFg[name] = c;
  deptBg[name] = c + "18";
  return { bg: deptBg[name], fg: c };
}

export default function CalendarPage() {
  const [jobs, setJobs] = useState<CalendarJob[]>([]);
  const [viewDate, setViewDate] = useState(new Date());

  useEffect(() => {
    getCalendar().then(d => setJobs(d.jobs || []));
  }, []);

  const year = viewDate.getFullYear();
  const mon = viewDate.getMonth();
  const firstDay = new Date(year, mon, 1).getDay();
  const daysInMonth = new Date(year, mon + 1, 0).getDate();
  const monthLabel = viewDate.toLocaleString("default", { month: "long", year: "numeric" });
  const today = new Date();

  const prev = () => setViewDate(new Date(year, mon - 1, 1));
  const next = () => setViewDate(new Date(year, mon + 1, 1));
  const goToday = () => setViewDate(new Date());

  // Build job map
  const jobDays: Record<number, CalendarJob[]> = {};
  jobs.forEach(j => {
    if (j.cadence === "daily") {
      for (let d = 1; d <= daysInMonth; d++) {
        jobDays[d] = [...(jobDays[d] || []), j];
      }
    } else if (j.cadence === "weekly") {
      for (let d = 1; d <= daysInMonth; d++) {
        if (new Date(year, mon, d).getDay() === 1) {
          jobDays[d] = [...(jobDays[d] || []), j];
        }
      }
    }
  });

  const isToday = (d: number) =>
    today.getFullYear() === year && today.getMonth() === mon && today.getDate() === d;

  // Count total events this month
  const totalEvents = Object.values(jobDays).reduce((n, arr) => n + arr.length, 0);

  return (
    <div className="calendar-page">
      {/* Header */}
      <div className="calendar-header">
        <div>
          <h1 className="text-lg font-semibold">Calendar</h1>
          <p className="text-xs mt-0.5" style={{ color: "var(--text-muted)" }}>
            {jobs.length} scheduled job{jobs.length === 1 ? "" : "s"} · {totalEvents} events this month
          </p>
        </div>
        <div className="calendar-nav">
          <button className="btn btn-secondary" onClick={prev} style={{ padding: "6px 12px", fontSize: 12 }}>
            ← Prev
          </button>
          <span className="calendar-month-label">{monthLabel}</span>
          <button className="btn btn-secondary" onClick={next} style={{ padding: "6px 12px", fontSize: 12 }}>
            Next →
          </button>
          <button className="btn btn-secondary" onClick={goToday} style={{ padding: "6px 12px", fontSize: 12 }}>
            Today
          </button>
        </div>
      </div>

      {/* Calendar grid */}
      <div className="calendar-grid">
        {/* Day headers */}
        <div className="calendar-weekdays">
          {WEEKDAYS.map(d => (
            <div key={d} className="calendar-weekday">{d}</div>
          ))}
        </div>

        {/* Empty cells before first day */}
        {Array.from({ length: firstDay }).map((_, i) => (
          <div key={`empty-${i}`} className="calendar-cell calendar-cell-empty" />
        ))}

        {/* Day cells */}
        {Array.from({ length: daysInMonth }).map((_, i) => {
          const day = i + 1;
          const dayJobs = jobDays[day] || [];
          const today_ = isToday(day);

          return (
            <div
              key={day}
              className={`calendar-cell ${today_ ? "calendar-cell-today" : ""}`}
            >
              <span className={`calendar-day-num ${today_ ? "calendar-day-today" : ""}`}>
                {day}
              </span>
              <div className="calendar-events">
                {dayJobs.slice(0, 3).map((j, ji) => {
                  const { fg, bg } = getDeptColor(j.department);
                  return (
                    <div
                      key={ji}
                      className="calendar-event"
                      style={{ background: bg, color: fg }}
                      title={`${j.department} / ${j.sop}`}
                    >
                      {j.department}/{j.sop}
                    </div>
                  );
                })}
                {dayJobs.length > 3 && (
                  <div className="calendar-event-more">+{dayJobs.length - 3} more</div>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Job list */}
      <div className="calendar-jobs">
        <h2 className="text-sm font-semibold mb-3" style={{ color: "var(--text-secondary)" }}>
          Scheduled Jobs
        </h2>
        <div className="flex flex-col gap-2">
          {jobs.map(j => {
            const { bg, fg } = getDeptColor(j.department);
            return (
              <div key={`${j.department}/${j.sop}`} className="card calendar-job-card">
                <div className="calendar-job-header">
                  <span className="calendar-job-dot" style={{ background: fg }} />
                  <span className="font-medium text-sm">{j.department}</span>
                  <span className="text-sm" style={{ color: "var(--text-muted)" }}>/ {j.sop}</span>
                  <span className="badge" style={{ background: bg, color: fg, fontSize: 10 }}>{j.cadence}</span>
                </div>
                <div className="calendar-job-footer">
                  <span className="text-xs" style={{ color: "var(--text-muted)" }}>
                    Last run: {j.last_run ? new Date(j.last_run).toLocaleDateString() : "never"}
                  </span>
                  {j.recent_runs && j.recent_runs.length > 0 && (
                    <div className="calendar-job-runs">
                      {j.recent_runs.slice(0, 5).map((r, i) => (
                        <span
                          key={i}
                          className={`badge ${r.status === "completed" ? "badge-green" : "badge-red"}`}
                          style={{ fontSize: 10 }}
                          title={`${r.status} · ${r.tokens.toLocaleString()} tokens · ${new Date(r.at).toLocaleDateString()}`}
                        >
                          {r.tokens >= 1000 ? `${(r.tokens / 1000).toFixed(0)}k` : r.tokens}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

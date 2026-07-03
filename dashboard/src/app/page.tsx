"use client";
import { useEffect, useState } from "react";
import Link from "next/link";

export default function Home() {
  const [dora, setDora] = useState<any>(null);
  const [sprints, setSprints] = useState<any[]>([]);
  const [heur, setHeur] = useState<any>(null);
  useEffect(() => {
    fetch("/api/dora").then(r => r.json()).then(setDora);
    fetch("/api/sprints").then(r => r.json()).then(setSprints);
    fetch("/api/heuristics").then(r => r.json()).then(setHeur);
  }, []);

  const streak = sprints.slice(0, 14).reverse();
  const activeCount = heur?.active?.length ?? 0;

  const nextRun = (() => {
    const d = new Date();
    d.setHours(2, 0, 0, 0);
    if (d < new Date()) d.setDate(d.getDate() + 1);
    return d;
  })();

  return (
    <div className="p-6 space-y-6">
      <div>
        <div className="text-sm uppercase text-gray-500">DORA</div>
        <div className="text-6xl font-bold">
          {dora?.latest?.tier ?? "—"}
        </div>
      </div>

      <div className="grid grid-cols-4 gap-3 text-sm">
        <Stat label="Deploy/day" v={dora?.latest?.deploy_freq?.toFixed(2)} />
        <Stat label="Lead time (d)" v={(dora?.latest?.lead_time_p50 / 86400).toFixed(1)} />
        <Stat label="CFR" v={(dora?.latest?.cfr * 100).toFixed(0) + "%"} />
        <Stat label="MTTR (h)" v={(dora?.latest?.mttr_p50 / 3600).toFixed(1)} />
      </div>

      <div>
        <div className="text-xs uppercase text-gray-500 mb-1">Last 14 sprints</div>
        <div className="flex gap-1">
          {streak.map((s: any) => (
            <div key={s.id}
                 title={`${s.id} — ${s.status}`}
                 className={
                   "w-3 h-3 rounded-full " +
                   (s.status === "completed" ? "bg-green-500"
                    : s.status === "needs_revision" ? "bg-yellow-500"
                    : "bg-red-500")
                 } />
          ))}
        </div>
      </div>

      <div className="grid grid-cols-3 gap-4">
        <div><Link href="/dora" className="text-blue-600">DORA</Link></div>
        <div><Link href="/sprints" className="text-blue-600">Sprints ({sprints.length})</Link></div>
        <div><Link href="/team" className="text-blue-600">Team</Link></div>
      </div>

      <div className="text-xs text-gray-500">
        Next sprint: {nextRun.toLocaleString()} · Active heuristics: {activeCount}
      </div>
    </div>
  );
}

function Stat({ label, v }: { label: string; v: any }) {
  return (
    <div className="border rounded p-3">
      <div className="text-xs uppercase text-gray-500">{label}</div>
      <div className="text-lg font-mono">{v ?? "—"}</div>
    </div>
  );
}

"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { Heading, Card, Badge } from "@/lib/ui";

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
    <div className="px-6 py-6 space-y-8">
      <div>
        <div className="text-sm uppercase tracking-wide" style={{ color: "var(--text-muted)" }}>DORA</div>
        <div className="text-6xl font-bold" style={{ color: "var(--text-primary)" }}>
          {dora?.latest?.tier ?? "—"}
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Stat label="Deploy/day" v={dora?.latest?.deploy_freq?.toFixed(2)} />
        <Stat label="Lead time (d)" v={(dora?.latest?.lead_time_p50 / 86400).toFixed(1)} />
        <Stat label="CFR" v={(dora?.latest?.cfr * 100).toFixed(0) + "%"} />
        <Stat label="MTTR (h)" v={(dora?.latest?.mttr_p50 / 3600).toFixed(1)} />
      </div>

      <div>
        <div className="text-xs uppercase tracking-wide mb-2" style={{ color: "var(--text-muted)" }}>Last 14 sprints</div>
        <div className="flex gap-1.5 flex-wrap">
          {streak.map((s: any) => (
            <div key={s.id}
                 title={`${s.id} — ${s.status}`}
                 className="w-3.5 h-3.5 rounded-full"
                 style={{
                   background:
                     s.status === "completed" ? "var(--green)"
                     : s.status === "needs_revision" ? "var(--yellow)"
                     : "var(--red)",
                 }} />
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {[
          { href: "/dora", label: "DORA" },
          { href: "/sprints", label: `Sprints (${sprints.length})` },
          { href: "/team", label: "Team" },
        ].map(({ href, label }) => (
          <Link key={href} href={href}>
            <Card hover className="text-center">
              <div className="font-medium" style={{ color: "var(--accent)" }}>{label}</div>
            </Card>
          </Link>
        ))}
      </div>

      <div className="text-xs" style={{ color: "var(--text-muted)" }}>
        Next sprint: {nextRun.toLocaleString()} · Active heuristics: {activeCount}
      </div>
    </div>
  );
}

function Stat({ label, v }: { label: string; v: any }) {
  return (
    <Card className="text-center">
      <div className="text-xs uppercase tracking-wide" style={{ color: "var(--text-muted)" }}>{label}</div>
      <div className="text-lg font-mono font-semibold mt-1" style={{ color: "var(--text-primary)" }}>{v ?? "—"}</div>
    </Card>
  );
}

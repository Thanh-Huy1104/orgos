"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { Heading, Card, Badge } from "@/lib/ui";

type Sprint = { id: string; branch: string; status: string; started_at: string;
                picked_issue: string };

export default function SprintsPage() {
  const [sprints, setSprints] = useState<Sprint[]>([]);
  useEffect(() => {
    fetch("/api/sprints").then(r => r.json()).then(setSprints);
  }, []);

  const statusVariant = (s: string) =>
    s === "completed" ? "green" : s === "needs_revision" ? "yellow" : s === "failed" ? "red" : s === "in_progress" ? "blue" : "gray";

  return (
    <div className="px-6 py-6 space-y-6">
      <Heading level={1}>Sprints</Heading>
      <Card className="overflow-x-auto p-0">
        <table className="w-full text-sm">
          <thead>
            <tr style={{ background: "var(--bg-secondary)", color: "var(--text-secondary)" }}>
              <th className="px-4 py-2.5 text-left font-medium">ID</th>
              <th className="px-4 py-2.5 text-left font-medium">Branch</th>
              <th className="px-4 py-2.5 text-left font-medium">Status</th>
              <th className="px-4 py-2.5 text-left font-medium">Started</th>
            </tr>
          </thead>
          <tbody>
            {sprints.map(s => (
              <tr key={s.id} className="border-t border-[var(--border)] hover:bg-[var(--bg-secondary)] transition-colors">
                <td className="px-4 py-2.5">
                  <Link href={`/sprints/${s.id}`} className="font-medium" style={{ color: "var(--blue)" }}>{s.id}</Link>
                </td>
                <td className="px-4 py-2.5 font-mono text-xs" style={{ color: "var(--text-secondary)" }}>{s.branch}</td>
                <td className="px-4 py-2.5"><Badge variant={statusVariant(s.status)}>{s.status}</Badge></td>
                <td className="px-4 py-2.5 text-xs" style={{ color: "var(--text-muted)" }}>{s.started_at?.slice(0, 19)?.replace("T", " ")}</td>
              </tr>
            ))}
            {sprints.length === 0 && (
              <tr><td colSpan={4} className="px-4 py-8 text-center" style={{ color: "var(--text-muted)" }}>No sprints yet</td></tr>
            )}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

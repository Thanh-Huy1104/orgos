"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { Heading, Card } from "@/lib/ui";

export default function LabPicker() {
  const [sprints, setSprints] = useState<any[]>([]);
  useEffect(() => {
    fetch("/api/sprints").then(r => r.json()).then(setSprints);
  }, []);
  return (
    <div className="px-6 py-6 space-y-6">
      <Heading level={1}>Counterfactual Lab</Heading>
      <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
        Pick a completed sprint to replay with a mutated brief.
      </p>
      <Card>
        <ul className="space-y-2">
          {sprints.filter((s: any) => s.status === "completed").map((s: any) => (
            <li key={s.id}>
              <Link href={`/lab/${s.id}`} className="text-sm font-medium hover:underline" style={{ color: "var(--blue)" }}>
                {s.id}
              </Link>
              <span className="text-xs ml-2" style={{ color: "var(--text-muted)" }}>{s.branch}</span>
            </li>
          ))}
          {sprints.filter((s: any) => s.status === "completed").length === 0 && (
            <li className="text-sm" style={{ color: "var(--text-muted)" }}>No completed sprints available.</li>
          )}
        </ul>
      </Card>
    </div>
  );
}

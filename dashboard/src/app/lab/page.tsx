"use client";
import { useEffect, useState } from "react";
import Link from "next/link";

export default function LabPicker() {
  const [sprints, setSprints] = useState<any[]>([]);
  useEffect(() => {
    fetch("/api/sprints").then(r => r.json()).then(setSprints);
  }, []);
  return (
    <div className="p-6">
      <h1 className="text-2xl mb-4">Counterfactual Lab</h1>
      <p className="text-sm text-gray-600 mb-4">
        Pick a completed sprint to replay with a mutated brief.
      </p>
      <ul className="space-y-1">
        {sprints.filter((s: any) => s.status === "completed").map((s: any) => (
          <li key={s.id}>
            <Link href={`/lab/${s.id}`} className="text-blue-600">{s.id}</Link>
            <span className="text-xs text-gray-500 ml-2">{s.branch}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

"use client";
import { useEffect, useState } from "react";
import Link from "next/link";

type Sprint = { id: string; branch: string; status: string; started_at: string;
                picked_issue: string };

export default function SprintsPage() {
  const [sprints, setSprints] = useState<Sprint[]>([]);
  useEffect(() => {
    fetch("/api/sprints").then(r => r.json()).then(setSprints);
  }, []);
  return (
    <div className="p-6">
      <h1 className="text-2xl mb-4">Sprints</h1>
      <table className="w-full text-sm">
        <thead><tr className="text-left">
          <th>ID</th><th>Branch</th><th>Status</th><th>Started</th>
        </tr></thead>
        <tbody>
          {sprints.map(s => (
            <tr key={s.id} className="border-t">
              <td className="py-1"><Link href={`/sprints/${s.id}`} className="text-blue-600">{s.id}</Link></td>
              <td>{s.branch}</td>
              <td>{s.status}</td>
              <td>{s.started_at?.slice(0, 19)?.replace("T", " ")}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

"use client";
import { useEffect, useState } from "react";
import dynamic from "next/dynamic";

const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), { ssr: false });

type Role = { name: string; tier: string; contribution: number };
type Edge = { from: string; to: string; weight: number };

type ADR = {
  id: number; kind: string; rationale: string; status: string;
  before_yaml: string; after_yaml: string; created_at: string;
};

export default function TeamPage() {
  const [topology, setTopology] = useState<{roles: Role[]; edges: Edge[]} | null>(null);
  const [adrs, setAdrs] = useState<Record<string, ADR[]> | null>(null);

  const refresh = () => {
    fetch("/api/team/topology").then(r => r.json()).then(setTopology);
    fetch("/api/team/adrs").then(r => r.json()).then(setAdrs);
  };
  useEffect(refresh, []);

  const act = async (id: number, verb: "approve" | "reject") => {
    await fetch(`/api/team/adrs/${id}/${verb}`, { method: "POST" });
    refresh();
  };

  if (!topology || !adrs) return <div className="p-6">Loading...</div>;

  const graph = {
    nodes: topology.roles.map(r => ({ id: r.name, name: r.name, tier: r.tier, val: 5 + r.contribution * 20 })),
    links: topology.edges.map(e => ({ source: e.from, target: e.to, width: 1 + e.weight * 4 })),
  };

  return (
    <div className="p-6 space-y-6">
      <div>
        <h2 className="text-xl mb-2">Role topology</h2>
        <div className="border h-96">
          <ForceGraph2D graphData={graph as any} nodeLabel="name" linkWidth={"width" as any} />
        </div>
      </div>
      <section>
        <h2 className="text-xl mb-2">ADRs</h2>
        {["pending", "approved", "applied", "rejected"].map(bucket => (
          <div key={bucket} className="mb-4">
            <h3 className="text-sm font-bold uppercase">{bucket}</h3>
            <ul className="space-y-2">
              {(adrs[bucket] ?? []).map(a => (
                <li key={a.id} className="border p-3 rounded">
                  <div className="flex justify-between">
                    <div>
                      <div className="font-mono text-sm">ADR-{String(a.id).padStart(3, "0")} · {a.kind}</div>
                      <div className="text-xs text-gray-600 mt-1">{a.rationale}</div>
                    </div>
                    {bucket === "pending" && (
                      <div className="space-x-2">
                        <button className="px-2 py-1 bg-green-600 text-white rounded" onClick={() => act(a.id, "approve")}>Approve</button>
                        <button className="px-2 py-1 bg-red-600 text-white rounded" onClick={() => act(a.id, "reject")}>Reject</button>
                      </div>
                    )}
                  </div>
                  <details className="mt-2">
                    <summary className="text-xs cursor-pointer">Show diff</summary>
                    <pre className="text-xs whitespace-pre-wrap bg-gray-50 p-2">{a.after_yaml}</pre>
                  </details>
                </li>
              ))}
              {(adrs[bucket] ?? []).length === 0 && <li className="text-gray-400 text-sm">None</li>}
            </ul>
          </div>
        ))}
      </section>
    </div>
  );
}

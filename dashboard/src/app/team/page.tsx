"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import dynamic from "next/dynamic";

// react-force-graph-2d has to load client-side only.
const ForceGraph2D = dynamic(
  () => import("react-force-graph-2d").then(m => m.default ?? (m as any)),
  { ssr: false, loading: () => <div className="p-4 text-xs text-gray-500">Loading graph…</div> },
);

type Role = { name: string; tier: string; contribution: number };
type Edge = { from: string; to: string; weight: number };

type ADR = {
  id: number; kind: string; rationale: string; status: string;
  before_yaml: string; after_yaml: string; created_at: string;
};

const TIER_COLOR: Record<string, string> = {
  orchestrator: "#6366F1",
  worker: "#059669",
  validator: "#D97706",
  publisher: "#DC2626",
};

export default function TeamPage() {
  const [topology, setTopology] = useState<{roles: Role[]; edges: Edge[]} | null>(null);
  const [adrs, setAdrs] = useState<Record<string, ADR[]> | null>(null);

  const graphBoxRef = useRef<HTMLDivElement>(null);
  const fgRef = useRef<any>(null);
  const [size, setSize] = useState({ w: 800, h: 500 });

  useEffect(() => {
    if (!graphBoxRef.current) return;
    const el = graphBoxRef.current;
    // Measure immediately so the first paint isn't 0x0.
    const rect = el.getBoundingClientRect();
    if (rect.width > 0) setSize({ w: Math.floor(rect.width), h: 500 });
    const ro = new ResizeObserver(entries => {
      const w = Math.floor(entries[0].contentRect.width);
      if (w > 0) setSize(prev => (prev.w === w ? prev : { w, h: 500 }));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const refresh = () => {
    fetch("/api/team/topology").then(r => r.json()).then(setTopology);
    fetch("/api/team/adrs").then(r => r.json()).then(setAdrs);
  };
  useEffect(refresh, []);

  const act = async (id: number, verb: "approve" | "reject") => {
    await fetch(`/api/team/adrs/${id}/${verb}`, { method: "POST" });
    refresh();
  };

  // Memoise so the physics sim isn't restarted on every render.
  const graphData = useMemo(() => {
    if (!topology) return { nodes: [], links: [] };
    return {
      nodes: topology.roles.map(r => ({
        id: r.name,
        name: r.name,
        tier: r.tier,
        color: TIER_COLOR[r.tier] ?? "#6B7280",
        val: 6 + r.contribution * 30,
        contribution: r.contribution,
      })),
      links: topology.edges.map(e => ({
        source: e.from,
        target: e.to,
        width: 1 + e.weight * 6,
      })),
    };
  }, [topology]);

  // Once the graph has data, ask force-graph to fit its view to the nodes so
  // nothing is offscreen at load.
  useEffect(() => {
    if (!fgRef.current || graphData.nodes.length === 0) return;
    const id = setTimeout(() => {
      try { fgRef.current?.zoomToFit?.(400, 60); } catch { /* first ticks not ready */ }
    }, 300);
    return () => clearTimeout(id);
  }, [graphData, size.w]);

  if (!topology || !adrs) return <div className="p-6">Loading...</div>;

  return (
    <div>
      <section className="mb-6">
        <h2 className="text-xl font-semibold mb-3">Role topology</h2>
        <div
          ref={graphBoxRef}
          className="border rounded bg-white w-full"
          style={{ height: 500, position: "relative", overflow: "hidden" }}
        >
          <ForceGraph2D
            ref={fgRef}
            graphData={graphData as any}
            width={size.w}
            height={size.h}
            nodeLabel={(n: any) => `${n.name}  (${(n.contribution * 100).toFixed(0)}%)`}
            nodeColor={(n: any) => n.color}
            nodeRelSize={5}
            linkWidth={(l: any) => l.width}
            linkColor={() => "rgba(120,120,120,0.4)"}
            linkDirectionalArrowLength={5}
            linkDirectionalArrowRelPos={0.9}
            cooldownTicks={80}
            enableNodeDrag={true}
          />
        </div>
        <div className="mt-2 text-xs text-gray-500 flex gap-4 flex-wrap">
          <LegendDot color="#6366F1" label="orchestrator" />
          <LegendDot color="#059669" label="worker" />
          <LegendDot color="#D97706" label="validator" />
          <LegendDot color="#DC2626" label="publisher" />
          <span>• node size = last-sprint contribution</span>
        </div>
      </section>

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

function LegendDot({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1">
      <span style={{ width: 8, height: 8, borderRadius: "50%", background: color, display: "inline-block" }} />
      {label}
    </span>
  );
}

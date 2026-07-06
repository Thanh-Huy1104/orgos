"use client";
import { useEffect, useRef, useState } from "react";
import * as d3 from "d3";
import { Heading, Card, Badge, Button } from "@/lib/ui";
import { Markdown } from "@/lib/markdown";

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

interface NodeDatum extends d3.SimulationNodeDatum {
  id: string;
  name: string;
  tier: string;
  color: string;
  val: number;
  contribution: number;
}

interface LinkDatum extends d3.SimulationLinkDatum<NodeDatum> {
  width: number;
}

export default function TeamPage() {
  const [topology, setTopology] = useState<{roles: Role[]; edges: Edge[]} | null>(null);
  const [adrs, setAdrs] = useState<Record<string, ADR[]> | null>(null);

  const graphBoxRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  const refresh = () => {
    fetch("/api/team/topology").then((r) => r.json()).then(setTopology);
    fetch("/api/team/adrs").then((r) => r.json()).then(setAdrs);
  };
  useEffect(refresh, []);

  const act = async (id: number, verb: "approve" | "reject") => {
    await fetch(`/api/team/adrs/${id}/${verb}`, { method: "POST" });
    refresh();
  };

  useEffect(() => {
    if (!topology || !svgRef.current || !graphBoxRef.current) return;

    const container = graphBoxRef.current;
    const getDims = () => ({
      w: Math.floor(container.getBoundingClientRect().width),
      h: Math.floor(container.getBoundingClientRect().height),
    });
    const dims = getDims();
    if (dims.w === 0 || dims.h === 0) return;

    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();
    svg.attr("viewBox", `0 0 ${dims.w} ${dims.h}`);

    const defs = svg.append("defs");
    defs.append("marker")
      .attr("id", "arrowhead")
      .attr("viewBox", "0 -5 10 10")
      .attr("refX", 22)
      .attr("refY", 0)
      .attr("markerWidth", 5)
      .attr("markerHeight", 5)
      .attr("orient", "auto")
      .append("path")
      .attr("d", "M0,-4L8,0L0,4")
      .attr("fill", "rgba(120,120,120,0.5)");

    const zoomGroup = svg.append("g");

    const nodes: NodeDatum[] = topology.roles.map((r) => ({
      id: r.name,
      name: r.name,
      tier: r.tier,
      color: TIER_COLOR[r.tier] ?? "#6B7280",
      val: 6 + r.contribution * 30,
      contribution: r.contribution,
      x: dims.w / 2 + (Math.random() - 0.5) * 200,
      y: dims.h / 2 + (Math.random() - 0.5) * 200,
    }));

    const links: LinkDatum[] = topology.edges.map((e) => ({
      source: e.from,
      target: e.to,
      width: 1 + e.weight * 6,
    }));

    const simulation = d3.forceSimulation<NodeDatum>(nodes)
      .force("link", d3.forceLink<NodeDatum, LinkDatum>(links).id((d) => d.id).distance(140))
      .force("charge", d3.forceManyBody().strength(-400))
      .force("center", d3.forceCenter(dims.w / 2, dims.h / 2))
      .force("collide", d3.forceCollide<NodeDatum>().radius((d) => d.val + 8));

    const linkGroup = zoomGroup.append("g")
      .selectAll<SVGLineElement, LinkDatum>("line")
      .data(links)
      .join("line")
      .attr("stroke", "rgba(120,120,120,0.4)")
      .attr("stroke-width", (d) => d.width)
      .attr("marker-end", "url(#arrowhead)");

    const nodeGroup = zoomGroup.append("g")
      .selectAll<SVGGElement, NodeDatum>("g")
      .data(nodes)
      .join("g")
      .attr("cursor", "grab");

    nodeGroup.call(
      d3.drag<SVGGElement, NodeDatum>()
        .on("start", (event, d) => {
          if (!event.active) simulation.alphaTarget(0.3).restart();
          d.fx = d.x;
          d.fy = d.y;
        })
        .on("drag", (event, d) => {
          d.fx = event.x;
          d.fy = event.y;
        })
        .on("end", (event, d) => {
          if (!event.active) simulation.alphaTarget(0);
          d.fx = null;
          d.fy = null;
        }) as any
    );

    nodeGroup.append("circle")
      .attr("r", (d) => d.val)
      .attr("fill", (d) => d.color)
      .attr("fill-opacity", 0.85)
      .attr("stroke", (d) => d.color)
      .attr("stroke-width", 1.5)
      .attr("stroke-opacity", 0.3);

    nodeGroup.append("text")
      .text((d) => d.name)
      .attr("text-anchor", "middle")
      .attr("dy", (d) => d.val + 14)
      .attr("font-size", 11)
      .attr("fill", "#6B6763")
      .attr("pointer-events", "none");

    simulation.on("tick", () => {
      linkGroup
        .attr("x1", (d) => (d.source as NodeDatum).x!)
        .attr("y1", (d) => (d.source as NodeDatum).y!)
        .attr("x2", (d) => (d.target as NodeDatum).x!)
        .attr("y2", (d) => (d.target as NodeDatum).y!);
      nodeGroup.attr("transform", (d) => `translate(${d.x},${d.y})`);
    });

    const zoomBehavior = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.2, 4])
      .on("zoom", (event) => {
        zoomGroup.attr("transform", event.transform.toString());
      });
    svg.call(zoomBehavior);

    const ro = new ResizeObserver(() => {
      const d = getDims();
      if (d.w === 0) return;
      svg.attr("viewBox", `0 0 ${d.w} ${d.h}`);
      simulation.force("center", d3.forceCenter(d.w / 2, d.h / 2));
      simulation.alpha(0.1).restart();
    });
    ro.observe(container);

    return () => {
      simulation.stop();
      ro.disconnect();
    };
  }, [topology]);

  if (!topology || !adrs) return <div className="px-6 py-6">Loading...</div>;

  return (
    <div className="px-6 py-6">
      <section className="mb-8">
        <Heading level={1} className="mb-3">Role topology</Heading>
        <div
          ref={graphBoxRef}
          className="border rounded-xl bg-white w-full"
          style={{ height: 500, position: "relative", overflow: "hidden", borderColor: "var(--border)" }}
        >
          <svg
            ref={svgRef}
            width="100%"
            height="100%"
            style={{ display: "block" }}
          />
        </div>
        <div className="mt-2 text-xs flex gap-4 flex-wrap" style={{ color: "var(--text-muted)" }}>
          <LegendDot color="#6366F1" label="orchestrator" />
          <LegendDot color="#059669" label="worker" />
          <LegendDot color="#D97706" label="validator" />
          <LegendDot color="#DC2626" label="publisher" />
          <span>• node size = contribution</span>
          <span>• drag nodes to rearrange</span>
        </div>
      </section>

      <section>
        <Heading level={1} className="mb-3">ADRs</Heading>
        {["pending", "approved", "applied", "rejected"].map((bucket) => (
          <div key={bucket} className="mb-4">
            <Heading level={3} className="uppercase mb-2">{bucket}</Heading>
            <div className="space-y-2">
              {(adrs[bucket] ?? []).map((a) => (
                <Card key={a.id}>
                  <div className="flex justify-between items-start gap-4">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-sm font-medium" style={{ color: "var(--text-primary)" }}>
                          ADR-{String(a.id).padStart(3, "0")}
                        </span>
                        <Badge variant="gray">{a.kind}</Badge>
                      </div>
                      <div className="text-xs mt-1" style={{ color: "var(--text-secondary)" }}><Markdown>{a.rationale}</Markdown></div>
                    </div>
                    {bucket === "pending" && (
                      <div className="flex gap-2 shrink-0">
                        <Button variant="primary" size="sm" onClick={() => act(a.id, "approve")}>Approve</Button>
                        <Button variant="danger" size="sm" onClick={() => act(a.id, "reject")}>Reject</Button>
                      </div>
                    )}
                  </div>
                  <details className="mt-2">
                    <summary className="text-xs cursor-pointer" style={{ color: "var(--text-muted)" }}>Show diff</summary>
                    <pre className="text-xs whitespace-pre-wrap rounded-lg p-3 mt-2" style={{ background: "var(--bg-secondary)" }}>{a.after_yaml}</pre>
                  </details>
                </Card>
              ))}
              {(adrs[bucket] ?? []).length === 0 && (
                <div className="text-sm py-2" style={{ color: "var(--text-muted)" }}>None</div>
              )}
            </div>
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

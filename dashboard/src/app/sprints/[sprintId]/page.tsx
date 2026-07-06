"use client";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { Heading, Card, Badge } from "@/lib/ui";

type Envelope = {
  role?: string;
  status?: string;
  summary?: string;
  artifacts?: string[];
  success_criteria_met?: boolean;
  requires_human_approval?: boolean;
  payload?: string;
  notes?: string | null;
};

type SprintData = {
  sprint?: {
    id: string;
    branch: string;
    status: string;
    picked_issue: string;
    started_at: string;
    updated_at: string;
  };
  envelopes?: Record<string, Envelope>;
  replay?: { parent_sprint_id?: string; mutation_kind?: string; mutation?: any } | null;
  error?: string;
};

const PHASE_ORDER = [
  "backlog", "brief", "engineering", "grade", "release", "dora", "retro",
];

const STATUS_VARIANT: Record<string, "green" | "yellow" | "red" | "blue" | "gray"> = {
  completed: "green",
  needs_revision: "yellow",
  failed: "red",
  in_progress: "blue",
  pending_release: "yellow",
};

function safeParsePayload(payload: string | undefined): any {
  if (!payload) return null;
  try {
    return JSON.parse(payload);
  } catch {
    return payload;
  }
}

export default function SprintDetail() {
  const { sprintId } = useParams<{ sprintId: string }>();
  const [data, setData] = useState<SprintData | null>(null);

  useEffect(() => {
    fetch(`/api/sprints/${sprintId}`).then(r => r.json()).then(setData);
  }, [sprintId]);

  if (!data) return <div className="px-6 py-6">Loading...</div>;
  if (data.error) return <div className="px-6 py-6" style={{ color: "var(--red)" }}>Error: {data.error}</div>;

  const envs = data.envelopes ?? {};
  const captured = PHASE_ORDER.filter(p => envs[p]);
  const missing = PHASE_ORDER.filter(p => !envs[p] && p !== "retro" && p !== "dora");
  const summary = envs["summary"];
  const status = data.sprint?.status ?? "in_progress";
  const variant = STATUS_VARIANT[status] ?? "gray";

  return (
    <div className="px-6 py-6 space-y-6 max-w-5xl">
      <div>
        <div className="text-xs uppercase tracking-wider mb-1" style={{ color: "var(--text-muted)" }}>Sprint</div>
        <div className="flex items-baseline gap-3">
          <Heading level={1}>{sprintId}</Heading>
          <Badge variant={variant}>{status}</Badge>
        </div>
        {data.sprint && (
          <div className="text-xs mt-1" style={{ color: "var(--text-secondary)" }}>
            branch <span className="font-mono">{data.sprint.branch}</span> ·
            started {data.sprint.started_at?.slice(0, 19).replace("T", " ")}
          </div>
        )}
        {data.replay && (
          <div className="text-xs mt-2" style={{ color: "var(--accent)" }}>
            replay of{" "}
            <a href={`/sprints/${data.replay.parent_sprint_id}`} className="underline">
              {data.replay.parent_sprint_id}
            </a>{" "}
            with mutation <span className="font-mono">{data.replay.mutation_kind}</span>
          </div>
        )}
      </div>

      {summary && <SummaryCard env={summary} />}

      {captured.length > (summary ? 1 : 0) && (
        <section>
          <Heading level={3} className="uppercase tracking-wider mb-3">Captured phases</Heading>
          <div className="space-y-3">
            {captured
              .filter(p => p !== "summary")
              .map(phase => <PhaseCard key={phase} phase={phase} env={envs[phase]} />)}
          </div>
        </section>
      )}

      {missing.length > 0 && (
        <section>
          <Heading level={3} className="uppercase tracking-wider mb-3">Phases not captured</Heading>
          <Card className="text-xs" style={{ background: "var(--bg-secondary)", color: "var(--text-secondary)" }}>
            {missing.join(", ")} — the sprint-lead delegated to subordinates but
            their raw output didn&apos;t contain a JSON envelope this parser
            could match. See the <span className="font-mono">summary</span> above for the
            authoritative sprint-lead account.
          </Card>
        </section>
      )}
    </div>
  );
}

function SummaryCard({ env }: { env: Envelope }) {
  return (
    <Card>
      <div className="flex items-baseline justify-between mb-2">
        <Heading level={2}>Sprint-Lead Summary</Heading>
        <div className="text-xs" style={{ color: "var(--text-muted)" }}>
          {env.status}
          {env.requires_human_approval ? " · needs approval" : ""}
        </div>
      </div>
      <div className="whitespace-pre-wrap text-sm leading-relaxed" style={{ color: "var(--text-secondary)" }}>{env.summary}</div>
      {env.notes && (
        <div className="mt-3 text-xs italic border-t pt-2" style={{ color: "var(--text-secondary)", borderColor: "var(--border)" }}>
          {env.notes}
        </div>
      )}
      {env.artifacts && env.artifacts.length > 0 && (
        <details className="mt-3">
          <summary className="text-xs cursor-pointer" style={{ color: "var(--text-muted)" }}>
            {env.artifacts.length} artifact{env.artifacts.length === 1 ? "" : "s"}
          </summary>
          <ul className="mt-2 space-y-1 text-xs font-mono">
            {env.artifacts.map((a, i) => (
              <li key={i} className="rounded-lg p-2 whitespace-pre-wrap break-all" style={{ background: "var(--bg-secondary)", border: "1px solid var(--border)" }}>{a}</li>
            ))}
          </ul>
        </details>
      )}
    </Card>
  );
}

function PhaseCard({ phase, env }: { phase: string; env: Envelope }) {
  const payload = safeParsePayload(env.payload);
  return (
    <Card>
      <div className="flex items-baseline justify-between mb-1">
        <div className="font-mono text-xs uppercase" style={{ color: "var(--text-primary)" }}>[{phase}]</div>
        <div className="text-xs" style={{ color: "var(--text-muted)" }}>
          {env.role} · {env.status}
        </div>
      </div>
      {env.summary && <div className="text-sm mb-2" style={{ color: "var(--text-secondary)" }}>{env.summary}</div>}
      {payload && (
        <details>
          <summary className="text-xs cursor-pointer" style={{ color: "var(--text-muted)" }}>payload</summary>
          <pre className="text-[11px] rounded-lg p-2 mt-2 whitespace-pre-wrap overflow-x-auto" style={{ background: "var(--bg-secondary)", border: "1px solid var(--border)" }}>
            {typeof payload === "string" ? payload : JSON.stringify(payload, null, 2)}
          </pre>
        </details>
      )}
    </Card>
  );
}

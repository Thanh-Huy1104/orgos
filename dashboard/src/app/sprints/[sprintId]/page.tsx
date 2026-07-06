"use client";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";

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

const STATUS_COLOR: Record<string, string> = {
  completed: "text-green-700 bg-green-50 border-green-200",
  needs_revision: "text-yellow-700 bg-yellow-50 border-yellow-200",
  failed: "text-red-700 bg-red-50 border-red-200",
  in_progress: "text-blue-700 bg-blue-50 border-blue-200",
  pending_release: "text-yellow-700 bg-yellow-50 border-yellow-200",
};

function safeParsePayload(payload: string | undefined): any {
  if (!payload) return null;
  try {
    return JSON.parse(payload);
  } catch {
    return payload;  // keep raw text if not JSON
  }
}

export default function SprintDetail() {
  const { sprintId } = useParams<{ sprintId: string }>();
  const [data, setData] = useState<SprintData | null>(null);

  useEffect(() => {
    fetch(`/api/sprints/${sprintId}`).then(r => r.json()).then(setData);
  }, [sprintId]);

  if (!data) return <div className="p-6">Loading...</div>;
  if (data.error) return <div className="p-6 text-red-600">Error: {data.error}</div>;

  const envs = data.envelopes ?? {};
  const captured = PHASE_ORDER.filter(p => envs[p]);
  const missing = PHASE_ORDER.filter(p => !envs[p] && p !== "retro" && p !== "dora");
  const summary = envs["summary"];
  const status = data.sprint?.status ?? "in_progress";
  const badge = STATUS_COLOR[status] ?? "text-gray-700 bg-gray-50 border-gray-200";

  return (
    <div className="p-6 space-y-6 max-w-5xl">
      <div>
        <div className="text-xs uppercase text-gray-500 tracking-wider mb-1">Sprint</div>
        <div className="flex items-baseline gap-3">
          <div className="font-mono text-2xl">{sprintId}</div>
          <span className={`text-xs px-2 py-0.5 rounded border ${badge}`}>{status}</span>
        </div>
        {data.sprint && (
          <div className="text-xs text-gray-500 mt-1">
            branch <span className="font-mono">{data.sprint.branch}</span> ·
            started {data.sprint.started_at?.slice(0, 19).replace("T", " ")}
          </div>
        )}
        {data.replay && (
          <div className="text-xs mt-2 text-purple-700">
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
          <h2 className="text-sm font-bold uppercase text-gray-500 tracking-wider mb-2">
            Captured phases
          </h2>
          <div className="space-y-3">
            {captured
              .filter(p => p !== "summary")
              .map(phase => <PhaseCard key={phase} phase={phase} env={envs[phase]} />)}
          </div>
        </section>
      )}

      {missing.length > 0 && (
        <section>
          <h2 className="text-sm font-bold uppercase text-gray-500 tracking-wider mb-2">
            Phases not captured
          </h2>
          <div className="text-xs text-gray-500 border p-3 rounded bg-gray-50">
            {missing.join(", ")} — the sprint-lead delegated to subordinates but
            their raw output didn&apos;t contain a JSON envelope this parser
            could match. See the <span className="font-mono">summary</span> above for the
            authoritative sprint-lead account.
          </div>
        </section>
      )}
    </div>
  );
}

function SummaryCard({ env }: { env: Envelope }) {
  return (
    <section className="border rounded p-4 bg-white">
      <div className="flex items-baseline justify-between mb-2">
        <h2 className="font-bold">Sprint-Lead Summary</h2>
        <span className="text-xs text-gray-500">
          {env.status}
          {env.requires_human_approval ? " · needs approval" : ""}
        </span>
      </div>
      <div className="whitespace-pre-wrap text-sm leading-relaxed">{env.summary}</div>
      {env.notes && (
        <div className="mt-3 text-xs text-gray-600 italic border-t pt-2">
          {env.notes}
        </div>
      )}
      {env.artifacts && env.artifacts.length > 0 && (
        <details className="mt-3">
          <summary className="text-xs text-gray-500 cursor-pointer">
            {env.artifacts.length} artifact{env.artifacts.length === 1 ? "" : "s"}
          </summary>
          <ul className="mt-2 space-y-1 text-xs font-mono">
            {env.artifacts.map((a, i) => (
              <li key={i} className="bg-gray-50 border rounded p-2 whitespace-pre-wrap break-all">{a}</li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}

function PhaseCard({ phase, env }: { phase: string; env: Envelope }) {
  const payload = safeParsePayload(env.payload);
  return (
    <div className="border rounded p-3 bg-white">
      <div className="flex items-baseline justify-between mb-1">
        <div className="font-mono text-xs uppercase text-gray-700">[{phase}]</div>
        <div className="text-xs text-gray-500">
          {env.role} · {env.status}
        </div>
      </div>
      {env.summary && <div className="text-sm mb-2">{env.summary}</div>}
      {payload && (
        <details>
          <summary className="text-xs text-gray-500 cursor-pointer">payload</summary>
          <pre className="text-[11px] bg-gray-50 border rounded p-2 mt-2 whitespace-pre-wrap overflow-x-auto">
            {typeof payload === "string" ? payload : JSON.stringify(payload, null, 2)}
          </pre>
        </details>
      )}
    </div>
  );
}

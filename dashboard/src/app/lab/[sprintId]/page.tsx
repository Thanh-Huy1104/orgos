"use client";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { Heading, Card, Button, Input } from "@/lib/ui";

type Mutation =
  | { kind: "swap_backlog_pick"; new_issue_id: string }
  | { kind: "inject_heuristic"; rule: string; why: string; tags: string[] }
  | { kind: "swap_role"; role_name: string; alt_model?: string };

export default function LabRunner() {
  const { sprintId } = useParams<{sprintId: string}>();
  const [original, setOriginal] = useState<any>(null);
  const [replay, setReplay] = useState<any>(null);
  const [mutKind, setMutKind] = useState<"swap_backlog_pick" | "inject_heuristic" | "swap_role">("inject_heuristic");
  const [args, setArgs] = useState<Record<string, string>>({ rule: "", why: "" });
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetch(`/api/sprints/${sprintId}`).then(r => r.json()).then(setOriginal);
  }, [sprintId]);

  const run = async () => {
    setBusy(true);
    const mutation_args: any = mutKind === "inject_heuristic"
      ? { rule: args.rule, why: args.why, tags: [] }
      : mutKind === "swap_backlog_pick" ? { new_issue_id: args.new_issue_id }
      : { role_name: args.role_name, alt_model: args.alt_model };
    const res = await fetch("/api/lab/replay", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ parent_sprint_id: sprintId, mutation_kind: mutKind, mutation_args }),
    }).then(r => r.json());
    if (res.replay_sprint_id) {
      const full = await fetch(`/api/sprints/${res.replay_sprint_id}`).then(r => r.json());
      setReplay(full);
    }
    setBusy(false);
  };

  return (
    <div className="px-6 py-6">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div>
          <Heading level={2}>Original ({sprintId})</Heading>
          {original ? (
            <pre className="text-xs rounded-lg p-3 mt-2 whitespace-pre-wrap max-h-[70vh] overflow-auto" style={{ background: "var(--bg-secondary)", border: "1px solid var(--border)" }}>
              {JSON.stringify(original?.envelopes, null, 2)}
            </pre>
          ) : <div className="mt-2" style={{ color: "var(--text-muted)" }}>Loading...</div>}
        </div>

        <div>
          <Heading level={2}>Replay</Heading>
          <Card className="mt-2 space-y-3">
            <Input label="Mutation type">
              <select value={mutKind} onChange={e => setMutKind(e.target.value as any)} className="input w-full mt-1">
                <option value="inject_heuristic">Inject heuristic</option>
                <option value="swap_backlog_pick">Swap backlog pick</option>
                <option value="swap_role">Swap role model</option>
              </select>
            </Input>
            {mutKind === "inject_heuristic" && <>
              <Input label="Rule" placeholder="rule" value={args.rule || ""} onChange={e => setArgs({...args, rule: e.target.value})} />
              <Input label="Why" placeholder="why" value={args.why || ""} onChange={e => setArgs({...args, why: e.target.value})} />
            </>}
            {mutKind === "swap_backlog_pick" && (
              <Input label="New issue ID" placeholder="new issue id" value={args.new_issue_id || ""} onChange={e => setArgs({...args, new_issue_id: e.target.value})} />
            )}
            {mutKind === "swap_role" && <>
              <Input label="Role name" placeholder="role name" value={args.role_name || ""} onChange={e => setArgs({...args, role_name: e.target.value})} />
              <Input label="Alt model" placeholder="alt model" value={args.alt_model || ""} onChange={e => setArgs({...args, alt_model: e.target.value})} />
            </>}
            <Button variant="primary" onClick={run} disabled={busy} className="w-full">
              {busy ? "Running..." : "Run replay"}
            </Button>
          </Card>
          {replay ? (
            <pre className="text-xs rounded-lg p-3 mt-3 whitespace-pre-wrap max-h-[60vh] overflow-auto" style={{ background: "var(--bg-secondary)", border: "1px solid var(--border)" }}>
              {JSON.stringify(replay?.envelopes, null, 2)}
            </pre>
          ) : <div className="text-sm mt-3" style={{ color: "var(--text-muted)" }}>Run a mutation to see the replay.</div>}
        </div>
      </div>
    </div>
  );
}

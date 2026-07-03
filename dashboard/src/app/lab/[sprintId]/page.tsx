"use client";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";

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
    <div className="p-6 grid grid-cols-2 gap-6">
      <div>
        <h2 className="text-lg font-bold mb-2">Original ({sprintId})</h2>
        {original ? <pre className="text-xs bg-gray-50 p-3 whitespace-pre-wrap max-h-[70vh] overflow-auto">
          {JSON.stringify(original?.envelopes, null, 2)}
        </pre> : <div>Loading...</div>}
      </div>
      <div>
        <h2 className="text-lg font-bold mb-2">Replay</h2>
        <div className="border p-3 mb-3 space-y-2">
          <select value={mutKind} onChange={e => setMutKind(e.target.value as any)}
                  className="border rounded p-1">
            <option value="inject_heuristic">Inject heuristic</option>
            <option value="swap_backlog_pick">Swap backlog pick</option>
            <option value="swap_role">Swap role model</option>
          </select>
          {mutKind === "inject_heuristic" && <>
            <input placeholder="rule" className="border p-1 w-full"
                   value={args.rule || ""} onChange={e => setArgs({...args, rule: e.target.value})} />
            <input placeholder="why" className="border p-1 w-full"
                   value={args.why || ""} onChange={e => setArgs({...args, why: e.target.value})} />
          </>}
          {mutKind === "swap_backlog_pick" && <input placeholder="new issue id"
            className="border p-1 w-full" value={args.new_issue_id || ""}
            onChange={e => setArgs({...args, new_issue_id: e.target.value})} />}
          {mutKind === "swap_role" && <>
            <input placeholder="role name" className="border p-1 w-full"
                   value={args.role_name || ""} onChange={e => setArgs({...args, role_name: e.target.value})} />
            <input placeholder="alt model" className="border p-1 w-full"
                   value={args.alt_model || ""} onChange={e => setArgs({...args, alt_model: e.target.value})} />
          </>}
          <button onClick={run} disabled={busy}
                  className="bg-blue-600 text-white rounded px-3 py-1">
            {busy ? "Running..." : "Run replay"}
          </button>
        </div>
        {replay ? <pre className="text-xs bg-gray-50 p-3 whitespace-pre-wrap max-h-[60vh] overflow-auto">
          {JSON.stringify(replay?.envelopes, null, 2)}
        </pre> : <div className="text-gray-400 text-sm">Run a mutation to see the replay.</div>}
      </div>
    </div>
  );
}

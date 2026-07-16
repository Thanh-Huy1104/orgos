"""Write a campaign_result.json for scrum runs on shutdown.

Waterfall writes campaign_result.json natively (DispatchResult). Scrum's
event-log-driven runtime doesn't — so the comparison harness had asymmetric
data. This helper reads live.jsonl + the board and writes a JSON in the same
shape as waterfall's output so both topologies are comparable.

Fields written (matching waterfall_runner.DispatchResult where possible):
  team_id, goal, model, executor
  started_at, ended_at, wall_seconds
  reason_stopped
  stories_created, stories_done, stories_blocked
  total_tokens_input, total_tokens_output
  per_story_results: list of {story_id, worker, commit_sha, tokens_in,
                              tokens_out, wall_seconds, status}
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_campaign_result(
    workspace: Any,
    board: Any,
    *,
    executor: str,
    reason_stopped: str,
) -> Path:
    """Read live.jsonl + board, aggregate, write campaign_result.json.
    Returns the path written. Safe to call multiple times.
    """
    root = workspace.root
    live_path = root / "live.jsonl"

    # ── event replay for tokens + timing ────────────────────────────────
    events: list[dict] = []
    if live_path.exists():
        for line in live_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    total_in = 0
    total_out = 0
    per_story: dict[str, dict] = {}
    for e in events:
        action = e.get("action", "")
        if action not in ("commit_landed", "story_no_commit"):
            continue
        sid = e.get("story_id", "")
        if not sid:
            continue
        rec = per_story.setdefault(sid, {
            "story_id": sid, "worker": "", "commit_sha": "",
            "tokens_in": 0, "tokens_out": 0, "wall_seconds": 0.0,
            "status": "unknown",
        })
        rec["worker"] = e.get("worker") or rec["worker"]
        rec["tokens_in"] += int(e.get("tokens_in", 0) or 0)
        rec["tokens_out"] += int(e.get("tokens_out", 0) or 0)
        rec["wall_seconds"] += float(e.get("wall_seconds", 0) or 0)
        if action == "commit_landed":
            rec["commit_sha"] = e.get("commit_sha", "")
            rec["status"] = "committed"
        elif action == "story_no_commit" and rec["status"] != "committed":
            rec["status"] = "no_commit"
        total_in += int(e.get("tokens_in", 0) or 0)
        total_out += int(e.get("tokens_out", 0) or 0)

    # ── wall time from event stream ─────────────────────────────────────
    started_at = events[0].get("timestamp", "") if events else ""
    ended_at = events[-1].get("timestamp", "") if events else ""

    # ── story counts from the authoritative board ───────────────────────
    all_states = ("draft", "refinement", "ready", "in_progress",
                  "review", "pending_acceptance", "done", "blocked")
    counts = {s: len(list(board.list_state(s))) for s in all_states}
    stories_created = sum(counts.values())
    stories_done = counts["done"]
    stories_blocked = counts["blocked"]

    # ── manifest for team_id / goal / model ─────────────────────────────
    m = None
    try:
        m = workspace.manifest()
    except Exception:
        pass

    # Sprint metadata (if the run went through real sprints)
    sprint_summary: list[dict] = []
    sprints_dir = root / "sprints"
    if sprints_dir.exists():
        for f in sorted(sprints_dir.glob("*.json")):
            try:
                sprint_summary.append(json.loads(f.read_text()))
            except json.JSONDecodeError:
                continue

    payload = {
        "sprints":               sprint_summary,
        "team_id":               getattr(m, "team_id", "") if m else "",
        "goal":                  getattr(m, "goal", "") if m else "",
        "model":                 getattr(m, "model", "") if m else "",
        "executor":              executor,
        "topology":              "scrum",
        "started_at":            started_at,
        "ended_at":              ended_at,
        "reason_stopped":        reason_stopped,
        "stories_created":       stories_created,
        "stories_done":          stories_done,
        "stories_blocked":       stories_blocked,
        "story_counts_by_state": counts,
        "total_tokens_input":    total_in,
        "total_tokens_output":   total_out,
        "per_story_results":     list(per_story.values()),
    }

    out = root / "campaign_result.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out

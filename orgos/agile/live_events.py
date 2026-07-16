"""Live activity feed — append-only JSONL per team.

The dispatcher (and waterfall runner) emit a small event per meaningful
action: story drafted, poker vote, discussion triggered, state transition,
worker assigned, commit landed, review verdict, wiki write.

The `orgos serve` HTTP endpoint tails this file and pushes new events to
the browser. Post-hoc, the same file can be read to rebuild a timeline.

File path: <workspace.root>/live.jsonl
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional


# ── Event types + emoji + short label ───────────────────────────────────
_EVENT_META: dict[str, tuple[str, str]] = {
    "goal_ingest_start":    ("🎯", "decomposing goal"),
    "goal_ingest_done":     ("📋", "backlog seeded"),
    "goal_ingest_failed":   ("💥", "decomposition failed"),
    "decomposition_warning":("⚠️ ", "decomposition warning"),
    "story_drafted":        ("📝", "story drafted"),
    "poker_vote":           ("🎲", "poker vote"),
    "poker_divergent":      ("💬", "discussion triggered"),
    "poker_converged":      ("🤝", "poker converged"),
    "refined_ready":        ("✅", "refined → READY"),
    "refined_blocked":      ("⛔", "refined → BLOCKED"),
    "story_pulled":         ("👷", "worker pulled story"),
    "commit_landed":        ("💾", "commit landed"),
    "story_no_commit":      ("🚫", "worker produced no commit"),
    "story_done_noop":      ("🎈", "already satisfied, no changes needed"),
    "story_review_pass":    ("👍", "peer review PASS"),
    "story_review_fail":    ("👎", "peer review FAIL"),
    "wiki_write":           ("📚", "wiki updated"),
    "state_transition":     ("➡️ ", "state transition"),
    "campaign_started":     ("🚀", "sprint started"),
    "campaign_finished":    ("🏁", "sprint finished"),
    "pr_opened":            ("🔀", "draft PR opened"),
    "pr_skipped":           ("🙅", "PR opening skipped"),
    "pr_failed":            ("❌", "PR opening failed"),
    "retro_started":        ("🪞", "retrospective starting"),
    "retro_written":        ("📓", "retrospective written"),
    "retro_failed":         ("⚠️ ", "retrospective failed"),
    "replan_started":       ("🗺 ", "PO replanning"),
    "replan_done":          ("🧭", "next sprint planned"),
    "replan_failed":        ("⚠️ ", "replan failed"),
    "multi_sprint_started": ("🎬", "multi-sprint run started"),
    "multi_sprint_finished":("🎌", "multi-sprint run finished"),
    "pr_feedback_ingested": ("💬", "PR review comments ingested"),
    "pr_feedback_none":     ("💤", "no new PR comments"),
    "pr_feedback_skipped":  ("🙅", "PR feedback ingestion skipped"),
    "pr_feedback_error":    ("⚠️ ", "PR feedback ingestion error"),
    "waterfall_phase":      ("🌊", "waterfall phase"),
    "merge_queued":         ("📮", "merge request queued"),
    "merge_completed":      ("🔗", "merge completed"),
    "merge_conflict":       ("💥", "merge conflict"),
    "merge_state_error":    ("⚠️ ", "merge post-transition failed"),
    "agent_started":        ("🟢", "agent online"),
    "agent_stopped":        ("🔴", "agent stopped"),
    "agent_crashed":        ("💀", "agent crashed"),
    "agent_restarted":      ("♻️ ", "agent restarted"),
    "subagent_spawned":     ("👶", "subagent spawned"),
    "scheduled_noop":       ("💤", "unrouted scheduled task"),
    "poker_failed":         ("⚠️ ", "poker failed"),
    "story_refined":        ("🃏", "story refined to ready"),
    "sprint_opened":        ("🚀", "sprint opened"),
    "sprint_closed":        ("🏁", "sprint closed"),
    "sprint_boundary_failed": ("⚠️ ", "sprint boundary failed"),
    "stories_accepted":     ("✅", "PO accepted stories"),
    "story_blocked_dod":    ("📚", "blocked: decision not in wiki"),
    "acceptance_failed":    ("⚠️ ", "acceptance ceremony failed"),
}


class EventEmitter:
    """Append-only event log for a team.

    Every emit() call:
      - writes one JSON object per line to <root>/live.jsonl
      - forwards to an optional `console_log` callback (defaults to print)

    Safe for the dispatcher to invoke — never raises; a failed write is
    swallowed so the run continues even if disk is full or the file is
    locked by the serve endpoint.
    """

    def __init__(
        self,
        workspace_root: Path,
        *,
        console_log: Optional[Callable[[str], None]] = None,
    ):
        self.path = Path(workspace_root) / "live.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.console_log = console_log or (lambda msg: print(msg, flush=True))

    def emit(self, action: str, **fields) -> None:
        emoji, label = _EVENT_META.get(action, ("•", action))
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "emoji": emoji,
            "label": label,
            **fields,
        }
        try:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except OSError:
            pass  # never let a bad write kill the run

        # Also print a human-readable one-liner
        story_id = fields.get("story_id", "")
        summary = fields.get("summary", "")
        extras = " ".join(
            f"{k}={v}" for k, v in fields.items()
            if k not in ("story_id", "summary", "emoji", "label", "timestamp")
            and not isinstance(v, (list, dict))
        )
        parts = [emoji, label]
        if story_id:
            parts.append(f"[{story_id}]")
        if summary:
            parts.append(summary)
        if extras:
            parts.append(f"({extras})")
        self.console_log(" ".join(parts))


def read_events(workspace_root: Path, since_iso: str = "") -> list[dict]:
    """Read events from live.jsonl, optionally filtered to `since_iso`."""
    p = Path(workspace_root) / "live.jsonl"
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if since_iso and entry.get("timestamp", "") <= since_iso:
            continue
        out.append(entry)
    return out

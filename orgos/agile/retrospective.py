"""Sprint retrospective — the mandatory Scrum ceremony at sprint end.

Spawns the scrum_master persona to write a retro entry to wiki/RETRO.md.
The retro is compact: what went well, what went wrong, ONE action item.
Every retro carries the mandatory three fields (author, timestamp, source).

Runs at the end of every Dispatcher sprint, regardless of stop reason
(backlog_empty, cap hit, wall_time_exceeded, no_worker_could_pull, etc.).
The team ALWAYS retros — that's the ceremony.

Failure to write the retro is logged as a WARN but does not fail the sprint.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from orgos.agile.board_store import BoardStore
from orgos.agile.live_events import EventEmitter
from orgos.agile.sprint import _extract_json_objects
from orgos.agile.team_workspace import TeamWorkspace
from orgos.spawn import TaskBrief, spawn
from orgos.subagents import scrum_master_role


_RETRO_BRIEF_TEMPLATE = """You are the Scrum Master. Write the sprint retrospective.

SPRINT
  sprint_id: {sprint_id}
  goal:      {goal}
  stopped:   {reason_stopped}
  duration:  ~{wall_minutes:.1f} minutes

RESULTS
  stories done:      {n_done}
  stories blocked:   {n_blocked}
  stories in flight: {n_inflight}
  tokens (in+out):   {tokens_total}

BOARD SNAPSHOT (final story states):
{board_summary}

RECENT AUDIT ACTIVITY (last 20 events):
{audit_tail}

RECENT WIKI DELTAS (last 20 entries from DECISIONS.md):
{wiki_tail}

YOUR JOB
Write a compact retrospective entry — 3 sections, plain markdown:

  ### What went well
  - 1-3 bullet points, concrete (e.g. "poker converged in one round on 4 of 6 stories")

  ### What went wrong / what surprised us
  - 1-3 bullet points, concrete (e.g. "story GS-03 sat in refinement for 40% of sprint due to divergent votes")
  - Be specific — vague retros are useless. Name the story_ids or events.

  ### Action item for next sprint
  - ONE actionable item. Not a wish. Something concrete a future team could DO.
  - Example: "split stories touching auth into smaller units before refinement"

OUTPUT ONLY THIS JSON (no prose, no fences):

{{
  "role": "scrum_master",
  "went_well": ["point 1", "point 2"],
  "went_wrong": ["point 1", "point 2"],
  "action_item": "one concrete action for next sprint"
}}
"""


def _board_summary(board: BoardStore) -> str:
    counts = board.counts_by_state()
    return " | ".join(f"{s}: {counts[s]}" for s in counts if counts[s] > 0)


def _audit_tail(workspace: TeamWorkspace, n: int = 20) -> str:
    """Read the last N lines of live.jsonl for the retro's audit context."""
    p = workspace.root / "live.jsonl"
    if not p.exists():
        return "(no audit events)"
    try:
        lines = p.read_text(encoding="utf-8").splitlines()[-n:]
    except OSError:
        return "(cannot read audit)"
    out = []
    for line in lines:
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts = (e.get("timestamp") or "")[11:19]
        sid = (e.get("story_id") or "")[:32]
        summary = (e.get("summary") or "")[:60]
        out.append(f"  {ts} {e.get('emoji','')} {e.get('label','')} [{sid}] {summary}")
    return "\n".join(out) if out else "(no audit events)"


def _wiki_tail(workspace: TeamWorkspace, n: int = 20) -> str:
    """Grab the last N lines from the SHARED wiki's DECISIONS.md."""
    p = workspace.source_repo / "wiki" / "DECISIONS.md"
    if not p.exists():
        return "(no wiki entries yet)"
    try:
        lines = p.read_text(encoding="utf-8").splitlines()[-n:]
    except OSError:
        return "(cannot read wiki)"
    return "\n".join(f"  {line}" for line in lines)


def run_retrospective(
    *,
    workspace: TeamWorkspace,
    board: BoardStore,
    emitter: EventEmitter,
    model: str,
    goal: str,
    reason_stopped: str,
    started_at: str,
    ended_at: str,
    tokens_total: int,
    token_accumulator: Optional[Callable[[Any], tuple[int, int]]] = None,
) -> dict:
    """Spawn the scrum_master to write a retro. Returns the retro dict.

    Never raises — a failed retro emits a warn event but doesn't break the sprint.
    """
    from datetime import datetime as _dt

    emitter.emit("retro_started", summary="scrum master writing retrospective")

    counts = board.counts_by_state()
    n_done = counts.get("done", 0)
    n_blocked = counts.get("blocked", 0)
    n_inflight = sum(counts.get(s, 0) for s in
                     ("draft", "refinement", "ready", "in_progress", "review"))

    try:
        start_dt = _dt.fromisoformat(started_at.replace("Z", "+00:00"))
        end_dt = _dt.fromisoformat(ended_at.replace("Z", "+00:00"))
        wall_minutes = (end_dt - start_dt).total_seconds() / 60.0
    except Exception:
        wall_minutes = 0.0

    brief_obj = _RETRO_BRIEF_TEMPLATE.format(
        sprint_id=workspace.team_id,
        goal=(goal or "")[:400],
        reason_stopped=reason_stopped,
        wall_minutes=wall_minutes,
        n_done=n_done,
        n_blocked=n_blocked,
        n_inflight=n_inflight,
        tokens_total=tokens_total,
        board_summary=_board_summary(board),
        audit_tail=_audit_tail(workspace),
        wiki_tail=_wiki_tail(workspace),
    )

    sm = scrum_master_role(model=model)
    sm.mcp_servers = []  # retro is prose-only, no tools needed

    brief = TaskBrief(
        objective=brief_obj,
        expected_output="Retro JSON with went_well, went_wrong, action_item.",
        success_criteria=["Valid JSON with three sections."],
    )

    retro: dict = {}
    try:
        result = spawn(sm, brief, run_budget_tokens=120_000)
        if token_accumulator:
            token_accumulator(result)
        for to in result.tasks_output:
            raw = getattr(to, "raw", "") or ""
            for blob in _extract_json_objects(raw):
                try:
                    data = json.loads(blob)
                except json.JSONDecodeError:
                    continue
                if isinstance(data, dict) and (
                    "went_well" in data or "action_item" in data
                ):
                    retro = data
                    break
            if retro:
                break
    except Exception as e:
        emitter.emit("retro_failed", error=str(e), summary=f"spawn error: {e}")
        return {}

    if not retro:
        emitter.emit("retro_failed", summary="scrum master produced no valid retro JSON")
        return {}

    # Write to wiki/RETRO.md — using wiki_write's 3-field validation form
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry = _format_retro_markdown(
        team_id=workspace.team_id,
        goal=goal,
        reason_stopped=reason_stopped,
        n_done=n_done,
        n_blocked=n_blocked,
        went_well=retro.get("went_well", []),
        went_wrong=retro.get("went_wrong", []),
        action_item=retro.get("action_item", ""),
        timestamp=ts,
    )

    # Write directly (RETRO.md doesn't have the 3-field enforcement DECISIONS.md
    # does, but we include the fields anyway for consistency).
    retro_path = workspace.source_repo / "wiki" / "RETRO.md"
    try:
        retro_path.parent.mkdir(parents=True, exist_ok=True)
        with retro_path.open("a", encoding="utf-8") as f:
            f.write(entry)
        emitter.emit(
            "retro_written",
            path=str(retro_path.relative_to(workspace.source_repo)),
            action_item=retro.get("action_item", "")[:150],
            summary=f"→ {retro_path.name}: {retro.get('action_item', '')[:80]}",
        )
    except OSError as e:
        emitter.emit("retro_failed", error=str(e),
                     summary=f"could not write RETRO.md: {e}")

    return retro


def _format_retro_markdown(
    *, team_id: str, goal: str, reason_stopped: str,
    n_done: int, n_blocked: int,
    went_well: list, went_wrong: list, action_item: str, timestamp: str,
) -> str:
    def _bullets(items):
        if not items:
            return "  - (none)"
        return "\n".join(f"  - {str(i).strip()}" for i in items)

    return f"""

## Retro — sprint {team_id}
- author: scrum_master
- timestamp: {timestamp}
- source: sprint:{team_id}
- goal: {(goal or '(none)')[:200]}
- stopped: {reason_stopped}
- stories done: {n_done}
- stories blocked: {n_blocked}

### What went well
{_bullets(went_well)}

### What went wrong
{_bullets(went_wrong)}

### Action item for next sprint
  {action_item.strip() if action_item else '(none)'}
"""

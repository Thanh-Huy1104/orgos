"""Between-sprints PO replanning.

Between sprints (multi-sprint mode), the PO reads:
  - the original goal
  - a summary of every sprint so far (done, blocked, retro action)
  - the current backlog (blocked, ready, refinement stories that carried over)
  - the last sprint's retro
and decides:
  {
    "goal_met": bool,               // stop the multi-sprint loop
    "reasoning": "…",
    "new_stories": [                // new stories to draft (same shape as ingest)
      {"title", "body", "type", "priority", "depends_on"}
    ],
    "unblock_stories": ["issue_id"], // blocked stories to transition back to draft
    "drop_stories": ["issue_id"]     // stories to abandon (mark as terminal blocked)
  }

Then the next sprint runs. If goal_met=true, the multi-sprint loop stops
early with reason="goal_met_declared_by_po".
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Optional

from orgos.agile.board_store import BoardStore, VALID_TYPES
from orgos.agile.goal_decomposer import _extract_json_arrays, _slugify
from orgos.agile.live_events import EventEmitter
from orgos.agile.sprint import _extract_json_objects
from orgos.agile.sprint_history import SprintRecord
from orgos.agile.team_workspace import TeamWorkspace
from orgos.spawn import TaskBrief, spawn
from orgos.subagents import po_role


_REPLAN_BRIEF_TEMPLATE = """You are the Product Owner. Sprint {last_sprint_num} just ended. Plan the next sprint.

ORIGINAL GOAL
{goal}

PRODUCT SPEC (from wiki/SPEC.md — the source of truth for what must be built)
{spec_block}

SPRINT HISTORY (most recent first)
{history_block}

CURRENT BACKLOG SNAPSHOT
{backlog_block}

RETRO HIGHLIGHTS FROM PRIOR SPRINTS
{prior_retros_block}

LAST SPRINT'S RETRO
  What went well:  {retro_well}
  What went wrong: {retro_wrong}
  Action item:     {retro_action}

YOUR JOB — decide the next sprint's plan.

1. Judge if the ORIGINAL GOAL is materially achieved. If yes, mark goal_met=true
   and provide a short "reasoning" — pointing at what was shipped and why it
   satisfies the goal. Nothing more is needed; the multi-sprint loop stops.

2. If the goal is NOT met, look at the CURRENT BACKLOG. Anything blocked that
   the retro's action item would unblock? Add it to `unblock_stories`. Anything
   still relevant?

3. Look at the ORIGINAL GOAL vs what's been shipped. Are there gaps? Draft
   NEW stories in `new_stories` (same shape as an initial decomposition):
     - Each has: title, body, type (architecture|test|security|feature|docs),
       priority (0-100), and optionally depends_on (a list of existing issue_ids
       that must be done first).
     - Only draft what the next sprint should actually pull.
     - If the retro flagged a story as too big, split it here.
     - Do NOT re-propose work that's already been done or is currently in the
       backlog — check the SPRINT HISTORY and BACKLOG SNAPSHOT above.

4. If any blocked stories are hopeless (wrong idea, superseded, or the retro
   suggests giving up), add them to `drop_stories` — they'll be walled off.

OUTPUT ONLY THIS JSON (no fences, no prose):

{{
  "role": "po",
  "goal_met": false,
  "reasoning": "short honest read of where we are vs the goal",
  "new_stories": [
    {{"title": "…", "body": "…", "type": "feature", "priority": 80, "depends_on": []}}
  ],
  "unblock_stories": [],
  "drop_stories": []
}}

Rules:
  - If goal_met=true, new_stories/unblock_stories/drop_stories can be empty.
  - Be honest — if the sprint made no progress, say so in reasoning.
  - Draft AT MOST 8 new stories. Sprints are timeboxed; don't over-plan.
"""


def _fmt_history(history: list[SprintRecord]) -> str:
    if not history:
        return "  (this is the first sprint)"
    lines = []
    for r in reversed(history):
        lines.append(
            f"  sprint {r.sprint_num}: done={r.stories_done} blocked={r.stories_blocked} "
            f"created={r.stories_created} stopped={r.reason_stopped} "
            f"retro-action=\"{r.retro_action_item[:100]}\""
        )
    return "\n".join(lines)


def _fmt_backlog(board: BoardStore) -> str:
    """One line per non-terminal, non-done story."""
    lines = []
    for state in ("blocked", "ready", "refinement", "draft", "in_progress", "review"):
        for s in board.list_state(state):
            title = s.title[:70]
            lines.append(f"  [{state:12s}] [{s.type:12s}] {s.issue_id[:36]:36s} p={s.priority:3d}  {title}")
    return "\n".join(lines) if lines else "  (backlog empty)"


def _load_spec(workspace: TeamWorkspace, max_chars: int = 6000) -> str:
    """Load wiki/SPEC.md so the PO stays anchored to the original spec on
    every replan. Look in the team's wiki first (persistent), then the
    source repo's wiki (initial `orgos start --spec-file` copy).

    Truncated to `max_chars` so the prompt stays bounded on large PRDs.
    """
    candidates = [
        getattr(workspace, "wiki_dir", None),
        (workspace.source_repo / "wiki") if getattr(workspace, "source_repo", None) else None,
        (workspace.integration_worktree / "wiki") if getattr(workspace, "integration_worktree", None) else None,
    ]
    for wiki_dir in candidates:
        if wiki_dir is None:
            continue
        p = wiki_dir / "SPEC.md"
        try:
            if p.exists():
                text = p.read_text(encoding="utf-8")
                if len(text) > max_chars:
                    head = text[: max_chars * 2 // 3]
                    tail = text[-max_chars // 3:]
                    return f"{head}\n\n… (spec truncated — {len(text)} chars total) …\n\n{tail}"
                return text
        except OSError:
            continue
    return "(no wiki/SPEC.md found — plan against the goal string above)"


def _prior_retros_block(workspace: TeamWorkspace, max_sprints: int = 5) -> str:
    """Pull the last N sprint retros out of wiki/RETRO.md so the PO can
    see recurring pain points, not just the most recent sprint's retro.
    """
    candidates = [
        getattr(workspace, "wiki_dir", None),
        (workspace.integration_worktree / "wiki") if getattr(workspace, "integration_worktree", None) else None,
        (workspace.source_repo / "wiki") if getattr(workspace, "source_repo", None) else None,
    ]
    text = ""
    for wiki_dir in candidates:
        if wiki_dir is None:
            continue
        p = wiki_dir / "RETRO.md"
        try:
            if p.exists():
                text = p.read_text(encoding="utf-8")
                if text.strip():
                    break
        except OSError:
            continue
    if not text.strip():
        return "  (no prior retros)"
    # Split by top-level H2 (## Retro …). Take the last N.
    blocks = []
    current: list[str] = []
    for line in text.splitlines():
        if line.startswith("## ") and current:
            blocks.append("\n".join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        blocks.append("\n".join(current))
    tail = blocks[-max_sprints:]
    # Compact each block: just keep the action items and any "went wrong" bullets
    out: list[str] = []
    for b in tail:
        head = b.splitlines()[0] if b.splitlines() else ""
        out.append(f"  {head}")
        for line in b.splitlines()[1:]:
            s = line.strip()
            if s.startswith("- ") or s.startswith("* "):
                out.append(f"    {s[:200]}")
            elif s.lower().startswith(("action", "went wrong")):
                out.append(f"    {s[:200]}")
    return "\n".join(out) if out else "  (retros present but no structured content parseable)"


def _draft_new_stories(
    board: BoardStore, new_stories: list, id_prefix: str,
) -> list[str]:
    """Add PO's newly-drafted stories to the board. Returns created issue_ids."""
    created: list[str] = []
    dep_specs: list[list] = []
    for i, s in enumerate(new_stories):
        if not isinstance(s, dict):
            continue
        title = str(s.get("title", "")).strip() or f"story-{i:02d}"
        body = str(s.get("body", "")).strip()
        story_type = str(s.get("type", "feature")).strip().lower()
        if story_type not in VALID_TYPES:
            story_type = "feature"
        try:
            priority = int(s.get("priority", 0))
        except (TypeError, ValueError):
            priority = 0

        raw_deps = s.get("depends_on") or []
        dep_specs.append(raw_deps if isinstance(raw_deps, list) else [])

        issue_id = f"{id_prefix}-{i:02d}-{_slugify(title)}"
        while board.exists(issue_id):
            issue_id = f"{issue_id}-{len(created)}"

        board.draft_story(
            issue_id=issue_id, title=title, body=body,
            story_type=story_type, priority=priority, actor="po",
        )
        created.append(issue_id)

    # Second pass: resolve dep indices (into new_stories list) OR literal issue_ids
    all_ids = created  # positional indices target new stories only
    for i, raw_deps in enumerate(dep_specs):
        if not raw_deps:
            continue
        resolved: list[str] = []
        for d in raw_deps:
            if isinstance(d, int) and 0 <= d < len(all_ids) and d != i:
                resolved.append(all_ids[d])
            elif isinstance(d, str):
                if d in all_ids or board.exists(d):
                    resolved.append(d)
        if resolved:
            story = board.read(created[i])
            story.depends_on = resolved
            board._write_story(story)
            board._audit(created[i], "po", "set_depends_on", deps=resolved)
    return created


def _unblock_stories(board: BoardStore, ids: list[str]) -> list[str]:
    """Transition blocked stories back to draft so they can re-refine."""
    unblocked = []
    for iid in ids:
        try:
            s = board.read(iid)
            if s.state == "blocked":
                board.transition(iid, "draft", actor="po",
                                 reason="unblocked_by_po_replan")
                unblocked.append(iid)
        except Exception:
            continue
    return unblocked


def _drop_stories(board: BoardStore, ids: list[str]) -> list[str]:
    """Wall off stories by transitioning to blocked with a 'dropped' reason."""
    dropped = []
    for iid in ids:
        try:
            s = board.read(iid)
            if s.state not in ("done",):
                # Force to blocked with a distinctive reason
                allowed = board.list_state(s.state)  # sanity
                target = "blocked" if s.state != "blocked" else None
                if target:
                    board.transition(iid, target, actor="po",
                                     reason="dropped_by_po_replan")
                board.add_comment(iid, author="po", body="Dropped by PO replan.")
                dropped.append(iid)
        except Exception:
            continue
    return dropped


def run_replan(
    *,
    workspace: TeamWorkspace,
    board: BoardStore,
    emitter: EventEmitter,
    model: str,
    goal: str,
    history: list[SprintRecord],
    last_retro: Optional[SprintRecord] = None,
    token_accumulator: Optional[Callable[[Any], tuple[int, int]]] = None,
) -> dict:
    """Spawn PO to replan for the next sprint. Returns the parsed decision.

    Never raises — a failed replan emits an event and returns
    {"goal_met": false, "new_stories": []} so the next sprint just proceeds
    with whatever's currently in the backlog.
    """
    emitter.emit("replan_started", summary="PO planning next sprint")

    last_num = history[-1].sprint_num if history else 0
    retro = last_retro or (history[-1] if history else None)
    retro_well = "; ".join(retro.retro_went_well) if retro else "(none)"
    retro_wrong = "; ".join(retro.retro_went_wrong) if retro else "(none)"
    retro_action = retro.retro_action_item if retro else "(none)"

    brief_obj = _REPLAN_BRIEF_TEMPLATE.format(
        last_sprint_num=last_num,
        goal=(goal or "")[:600],
        spec_block=_load_spec(workspace),
        history_block=_fmt_history(history),
        backlog_block=_fmt_backlog(board),
        prior_retros_block=_prior_retros_block(workspace),
        retro_well=retro_well[:400],
        retro_wrong=retro_wrong[:400],
        retro_action=retro_action[:300],
    )

    po = po_role(model=model)
    po.mcp_servers = []

    brief = TaskBrief(
        objective=brief_obj,
        expected_output="Replan JSON with goal_met, new_stories, unblock_stories, drop_stories.",
        success_criteria=["Valid JSON."],
    )

    decision: dict = {}
    try:
        result = spawn(po, brief, run_budget_tokens=300_000)
        if token_accumulator:
            token_accumulator(result)
        for to in result.tasks_output:
            raw = getattr(to, "raw", "") or ""
            for blob in _extract_json_objects(raw):
                try:
                    data = json.loads(blob)
                except json.JSONDecodeError:
                    continue
                if isinstance(data, dict) and ("goal_met" in data or "new_stories" in data):
                    decision = data
                    break
                # Envelope-wrapped form: {"payload": {...}}
                payload = data.get("payload") if isinstance(data, dict) else None
                if isinstance(payload, dict) and ("goal_met" in payload or "new_stories" in payload):
                    decision = payload
                    break
            if decision:
                break
    except Exception as e:
        emitter.emit("replan_failed", error=str(e), summary=f"spawn error: {e}")
        return {"goal_met": False, "new_stories": [], "unblock_stories": [], "drop_stories": []}

    if not decision:
        emitter.emit("replan_failed", summary="PO produced no valid replan JSON")
        return {"goal_met": False, "new_stories": [], "unblock_stories": [], "drop_stories": []}

    # Apply the decision to the board
    new_ids = _draft_new_stories(
        board, decision.get("new_stories", []) or [],
        id_prefix=f"S{last_num + 1}",
    )
    unblocked = _unblock_stories(
        board, decision.get("unblock_stories", []) or [],
    )
    dropped = _drop_stories(
        board, decision.get("drop_stories", []) or [],
    )

    goal_met = bool(decision.get("goal_met", False))
    reasoning = str(decision.get("reasoning", ""))[:300]

    emitter.emit(
        "replan_done",
        goal_met=goal_met,
        n_new=len(new_ids),
        n_unblocked=len(unblocked),
        n_dropped=len(dropped),
        summary=(
            (f"goal MET — {reasoning}" if goal_met
             else f"drafted {len(new_ids)} new, unblocked {len(unblocked)}, dropped {len(dropped)}"
             + (f" — {reasoning}" if reasoning else ""))[:300]
        ),
    )

    return {
        "goal_met": goal_met,
        "reasoning": reasoning,
        "new_story_ids": new_ids,
        "unblocked_story_ids": unblocked,
        "dropped_story_ids": dropped,
    }

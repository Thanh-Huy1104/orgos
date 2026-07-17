"""Sprint model for real-Scrum boundary tracking.

Distinct from the legacy `sprint.py` (single-story per Sprint, used by
waterfall). This module handles multi-story time-boxed iterations:

  sprint 0 (pre-planning) → sprint 1 → sprint 2 → ...

Each sprint has:
  - number (1, 2, 3...)
  - started_at / ended_at (ISO UTC)
  - committed_backlog: list of story issue_ids the team pulled into the sprint
  - stories_done_in_sprint, points_completed (populated at close)

Sprints are stored as JSON at `<workspace>/sprints/<n>.json`. The current
sprint number lives at `<workspace>/current_sprint.txt` for cheap lookup.

Design choice: sprint 0 is a special "pre-sprint" state where the team is
still bootstrapping (PO decomposing, SM refining first backlog). Stories
drafted before any sprint has been opened carry `sprint_number = 0` and are
NOT pullable. The first `open_sprint(workspace, po_selection_fn)` starts
sprint 1 and assigns a subset of ready stories to it.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from orgos.agile.spe import sprint_process_efficiency


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Sprint:
    number: int
    started_at: str
    ended_at: str = ""
    committed_backlog: list[str] = field(default_factory=list)   # story issue_ids
    stories_done: list[str] = field(default_factory=list)         # populated at close
    points_completed: int = 0                                     # velocity
    duration_hours: float = 0.0                                   # actual wall-clock, set at close
    final_commit: int = 0                                         # Σ points of committed non-dropped stories
    spe: float = 0.0                                              # Sprint Process Efficiency, set at close
    reason_closed: str = ""

    @property
    def is_open(self) -> bool:
        return not self.ended_at


def _sprints_dir(workspace: Any) -> Path:
    d = workspace.root / "sprints"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _current_sprint_marker(workspace: Any) -> Path:
    return workspace.root / "current_sprint.txt"


def current_sprint_number(workspace: Any) -> int:
    p = _current_sprint_marker(workspace)
    if not p.exists():
        return 0
    try:
        return int(p.read_text().strip())
    except (ValueError, OSError):
        return 0


def _set_current_sprint_number(workspace: Any, n: int) -> None:
    _current_sprint_marker(workspace).write_text(str(n))


def read_sprint(workspace: Any, number: int) -> Optional[Sprint]:
    p = _sprints_dir(workspace) / f"{number}.json"
    if not p.exists():
        return None
    d = json.loads(p.read_text())
    return Sprint(**d)


def _write_sprint(workspace: Any, sprint: Sprint) -> Path:
    p = _sprints_dir(workspace) / f"{sprint.number}.json"
    p.write_text(json.dumps(asdict(sprint), indent=2), encoding="utf-8")
    return p


def open_sprint(
    workspace: Any,
    board: Any,
    *,
    velocity_target: int = 6,
    select_stories: Optional[Callable[[list], list]] = None,
) -> Sprint:
    """Close the current sprint if open, open the next one, run planning.

    Planning:
      1. Pick up to `velocity_target` stories from state='ready' whose
         sprint_number is 0 (not yet committed to a sprint).
      2. Sort by priority DESC and take the top N.
      3. Assign them the new sprint's number.
      4. Persist.

    If `select_stories` is provided it overrides the default priority-sort
    (used for tests). It receives the candidate list and returns a subset.
    """
    prev = current_sprint_number(workspace)
    # Close the previous sprint (if any and still open)
    if prev > 0:
        p = read_sprint(workspace, prev)
        if p and p.is_open:
            close_sprint(workspace, board, reason="rolled_over")

    new_num = prev + 1
    candidates = [
        s for s in board.list_state("ready")
        if getattr(s, "sprint_number", 0) == 0
    ]
    if select_stories is not None:
        picked = select_stories(candidates)
    else:
        candidates.sort(key=lambda s: -int(getattr(s, "priority", 0) or 0))
        picked = candidates[:velocity_target]

    for story in picked:
        board.set_sprint_number(story.issue_id, new_num, actor="po")

    sprint = Sprint(
        number=new_num,
        started_at=_now_iso(),
        committed_backlog=[s.issue_id for s in picked],
    )
    _write_sprint(workspace, sprint)
    _set_current_sprint_number(workspace, new_num)
    return sprint


def close_sprint(
    workspace: Any,
    board: Any,
    *,
    reason: str = "scheduled",
) -> Optional[Sprint]:
    """Close the current sprint. Populates stories_done + points_completed
    from the board. Returns the closed sprint (or None if none was open).
    """
    n = current_sprint_number(workspace)
    if n == 0:
        return None
    sprint = read_sprint(workspace, n)
    if sprint is None or not sprint.is_open:
        return sprint

    # Populate metrics from the board. Also roll over any story that didn't
    # reach `done` — reset its sprint_number to 0 so the next planner can pick
    # it up. Without this, unfinished stories are stranded (real Scrum practice
    # would move them back to the product backlog).
    done_ids: list[str] = []
    points = 0
    committed_stories = []
    rolled_over = 0
    for sid in sprint.committed_backlog:
        try:
            story = board.read(sid)
        except Exception:
            continue
        committed_stories.append(story)
        if story.state == "done":
            done_ids.append(sid)
            points += int(getattr(story, "points", 0) or 0)
        else:
            # Roll back to the un-committed pool so sprint N+1 can re-plan it.
            try:
                board.set_sprint_number(sid, 0, actor="scrum_master")
                rolled_over += 1
            except Exception:
                pass

    sprint.stories_done = done_ids
    sprint.points_completed = points
    sprint.ended_at = _now_iso()
    sprint.reason_closed = reason

    # Sprint Process Efficiency — time-proportional delivery metric. Duration
    # is the actual wall-clock the sprint ran (started_at → ended_at).
    started = _parse_iso(sprint.started_at)
    ended = _parse_iso(sprint.ended_at)
    duration_hours = 0.0
    if started is not None and ended is not None:
        duration_hours = max((ended - started).total_seconds() / 3600.0, 0.0)
    result = sprint_process_efficiency(
        committed_stories, duration_hours=duration_hours,
    )
    sprint.duration_hours = result["duration_hours"]
    sprint.final_commit = result["final_commit"]
    sprint.spe = result["spe"]

    _write_sprint(workspace, sprint)
    return sprint


def _parse_iso(ts: str) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None

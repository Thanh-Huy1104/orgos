"""Sprint history — per-team log of every sprint that ran.

Stored append-only at .orgos_teams/<id>/sprints.jsonl. One JSON object per
completed sprint with the numbers that matter for the multi-sprint story:
what shipped, what got blocked, what the retro said to do next.

The multi-sprint runner uses this to (a) pass the previous retro's action
item into the next PO plan, (b) detect stagnation ("last 2 sprints shipped
nothing new — stop"), and (c) render a timeline in the report.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass
class SprintRecord:
    sprint_num: int              # 1-indexed within the team
    started_at: str              # ISO timestamp
    ended_at: str
    reason_stopped: str
    stories_done: int
    stories_blocked: int
    stories_created: int
    tokens_input: int
    tokens_output: int
    spe: float = 0.0             # Sprint Process Efficiency (0.0 if not computed)
    pr_url: str = ""
    retro_action_item: str = ""  # extracted from the sprint's retro
    retro_went_well: list[str] = field(default_factory=list)
    retro_went_wrong: list[str] = field(default_factory=list)


def history_path(workspace_root: Path) -> Path:
    return Path(workspace_root) / "sprints.jsonl"


def append_record(workspace_root: Path, record: SprintRecord) -> None:
    p = history_path(workspace_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(record)) + "\n")


def read_history(workspace_root: Path) -> list[SprintRecord]:
    p = history_path(workspace_root)
    if not p.exists():
        return []
    out: list[SprintRecord] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        try:
            out.append(SprintRecord(**data))
        except TypeError:
            # Forward-compat: ignore extra fields
            known = {f.name for f in SprintRecord.__dataclass_fields__.values()}
            filtered = {k: v for k, v in data.items() if k in known}
            try:
                out.append(SprintRecord(**filtered))
            except TypeError:
                continue
    return out


def next_sprint_num(workspace_root: Path) -> int:
    """1 if no prior sprints; otherwise (last num + 1)."""
    hist = read_history(workspace_root)
    return (hist[-1].sprint_num + 1) if hist else 1


def stagnation_detected(
    workspace_root: Path, *, window: int = 2, min_done: int = 1,
) -> bool:
    """True if the last `window` sprints produced fewer than `min_done` stories each.

    Signals to the multi-sprint loop that the team is stuck and further
    sprints are unlikely to help — stop for human intervention.
    """
    hist = read_history(workspace_root)
    if len(hist) < window:
        return False
    return all(s.stories_done < min_done for s in hist[-window:])

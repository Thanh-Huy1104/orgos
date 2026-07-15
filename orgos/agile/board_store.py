"""Board substrate — filesystem-backed multi-story blackboard.

One BoardStore instance = one team's board.
  - Story = one JSON file at board/stories/<issue_id>.json
  - Audit trail per story at board/audit/<issue_id>.jsonl
  - Index at board/index.json for O(1) list-by-state / list-by-type

Every mutation is atomic (temp file + rename). Every mutation appends to
the audit trail so we have full provenance for the report.

State machine:

    draft ─→ refinement ─→ ready ─→ in_progress ─→ review ─→ done
                                         │              │
                                         └── blocked ←──┘

Story fields:
  issue_id      : unique per team (kebab-case)
  title         : one line
  body          : markdown, spec of the work
  state         : one of the above
  type          : architecture | test | security | feature | docs
  priority      : int; higher = pull first (default 0)
  points        : Fibonacci int | None (set by planning poker)
  votes         : list[{voter, points, justification, timestamp}]
  signoffs      : {role: True} — set during refinement
  assignee      : role name or ""
  refinement_rounds : int
  comments      : list[{author, timestamp, body}]
  wiki_touched  : bool — set True when architect writes wiki during work
  commit_sha    : set when the story lands a commit
  created_at    : ISO
  updated_at    : ISO
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


VALID_STATES = ("draft", "refinement", "ready", "in_progress", "review", "done", "blocked")
VALID_TYPES = ("architecture", "test", "security", "feature", "docs")

# state machine — key = current state, value = allowed next states
TRANSITIONS: dict[str, tuple[str, ...]] = {
    "draft":       ("refinement", "blocked"),
    "refinement":  ("ready", "draft", "blocked"),
    "ready":       ("in_progress", "blocked"),
    "in_progress": ("review", "blocked", "ready"),   # ready → return-to-queue
    "review":      ("done", "in_progress", "blocked"),
    "done":        (),   # terminal
    "blocked":     ("draft", "refinement", "ready", "in_progress", "review"),
}


class BoardError(RuntimeError):
    pass


class InvalidTransition(BoardError):
    pass


@dataclass
class Story:
    issue_id: str
    title: str
    body: str
    state: str
    type: str
    priority: int = 0
    points: Optional[int] = None
    votes: list[dict] = field(default_factory=list)
    signoffs: dict[str, bool] = field(default_factory=dict)
    assignee: str = ""
    refinement_rounds: int = 0
    comments: list[dict] = field(default_factory=list)
    wiki_touched: bool = False
    commit_sha: str = ""
    created_at: str = ""
    updated_at: str = ""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write(path: Path, text: str) -> None:
    """Atomic write via temp-file + rename in the same directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=".tmp-", suffix=path.suffix, dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class BoardStore:
    """Filesystem-backed board for one team instance.

    Lives at <team_root>/board/.
    """

    def __init__(self, board_dir: Path):
        self.root = Path(board_dir)
        self.stories_dir = self.root / "stories"
        self.audit_dir = self.root / "audit"
        self.index_path = self.root / "index.json"
        self.stories_dir.mkdir(parents=True, exist_ok=True)
        self.audit_dir.mkdir(parents=True, exist_ok=True)
        if not self.index_path.exists():
            self._write_index({})

    # ── Index ────────────────────────────────────────────────────────────

    def _read_index(self) -> dict:
        try:
            return json.loads(self.index_path.read_text())
        except Exception:
            return {}

    def _write_index(self, idx: dict) -> None:
        _atomic_write(self.index_path, json.dumps(idx, indent=2))

    def _index_update(self, issue_id: str, state: str, story_type: str,
                      priority: int) -> None:
        idx = self._read_index()
        idx[issue_id] = {"state": state, "type": story_type, "priority": priority}
        self._write_index(idx)

    def _index_remove(self, issue_id: str) -> None:
        idx = self._read_index()
        idx.pop(issue_id, None)
        self._write_index(idx)

    # ── Audit ────────────────────────────────────────────────────────────

    def _audit(self, issue_id: str, actor: str, action: str, **extra) -> None:
        entry = {
            "timestamp": _now_iso(),
            "actor": actor,
            "action": action,
            **extra,
        }
        path = self.audit_dir / f"{issue_id}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def audit_trail(self, issue_id: str) -> list[dict]:
        path = self.audit_dir / f"{issue_id}.jsonl"
        if not path.exists():
            return []
        out = []
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out

    # ── Story CRUD ───────────────────────────────────────────────────────

    def _story_path(self, issue_id: str) -> Path:
        return self.stories_dir / f"{issue_id}.json"

    def _write_story(self, story: Story) -> None:
        story.updated_at = _now_iso()
        _atomic_write(self._story_path(story.issue_id),
                      json.dumps(asdict(story), indent=2))
        self._index_update(story.issue_id, story.state, story.type, story.priority)

    def read(self, issue_id: str) -> Story:
        p = self._story_path(issue_id)
        if not p.exists():
            raise BoardError(f"no such story: {issue_id}")
        data = json.loads(p.read_text())
        return Story(**data)

    def exists(self, issue_id: str) -> bool:
        return self._story_path(issue_id).exists()

    def all_stories(self) -> list[Story]:
        return [self.read(iid) for iid in sorted(self._read_index().keys())]

    def list_state(self, state: str) -> list[Story]:
        if state not in VALID_STATES:
            raise BoardError(f"invalid state: {state}")
        idx = self._read_index()
        ids = [iid for iid, meta in idx.items() if meta.get("state") == state]
        return sorted(
            (self.read(iid) for iid in ids),
            key=lambda s: (-s.priority, s.created_at),
        )

    def list_ready_for_type(self, worker_type: str) -> list[Story]:
        """READY stories a worker of `worker_type` can pull.

        Type-matching rules:
          architecture worker → architecture, feature
          test         worker → test
          security     worker → security
          docs         → any worker (fallback)
          feature      → architecture worker OR any worker if starved
        """
        ready = self.list_state("ready")
        # Primary matches by type
        primary: dict[str, tuple[str, ...]] = {
            "architecture": ("architecture", "feature"),
            "test":         ("test",),
            "security":     ("security",),
            "devsecops":    ("security",),
            "docs":         ("docs",),
        }
        allowed = primary.get(worker_type, ("architecture", "test", "security",
                                             "feature", "docs"))
        return [s for s in ready if s.type in allowed]

    # ── Draft (create) ───────────────────────────────────────────────────

    def draft_story(
        self,
        *,
        issue_id: str,
        title: str,
        body: str,
        story_type: str,
        priority: int = 0,
        actor: str = "po",
    ) -> Story:
        if story_type not in VALID_TYPES:
            raise BoardError(
                f"invalid type: {story_type!r}. Valid: {VALID_TYPES}"
            )
        if self.exists(issue_id):
            raise BoardError(f"story already exists: {issue_id}")
        now = _now_iso()
        story = Story(
            issue_id=issue_id,
            title=title.strip(),
            body=body,
            state="draft",
            type=story_type,
            priority=priority,
            created_at=now,
            updated_at=now,
        )
        self._write_story(story)
        self._audit(issue_id, actor, "draft_story",
                    title=title, story_type=story_type, priority=priority)
        return story

    # ── State transition ────────────────────────────────────────────────

    def transition(
        self,
        issue_id: str,
        new_state: str,
        *,
        actor: str,
        reason: str = "",
    ) -> Story:
        story = self.read(issue_id)
        if new_state not in VALID_STATES:
            raise InvalidTransition(f"invalid state: {new_state!r}")
        allowed = TRANSITIONS.get(story.state, ())
        if new_state not in allowed:
            raise InvalidTransition(
                f"cannot go from {story.state!r} to {new_state!r} "
                f"(allowed: {allowed})"
            )
        old = story.state
        story.state = new_state
        self._write_story(story)
        self._audit(issue_id, actor, "transition",
                    from_state=old, to_state=new_state, reason=reason)
        return story

    # ── Refinement bits ─────────────────────────────────────────────────

    def add_signoff(self, issue_id: str, role: str, actor: str) -> Story:
        story = self.read(issue_id)
        story.signoffs[role] = True
        self._write_story(story)
        self._audit(issue_id, actor, "signoff", role=role)
        return story

    def add_comment(self, issue_id: str, author: str, body: str) -> Story:
        story = self.read(issue_id)
        story.comments.append({
            "author": author, "timestamp": _now_iso(), "body": body,
        })
        self._write_story(story)
        self._audit(issue_id, author, "comment", body_len=len(body))
        return story

    def add_poker_vote(
        self,
        issue_id: str,
        voter: str,
        points: int,
        justification: str,
    ) -> Story:
        story = self.read(issue_id)
        # Overwrite any previous vote by the same voter (for re-votes).
        story.votes = [v for v in story.votes if v.get("voter") != voter]
        story.votes.append({
            "voter": voter, "points": points, "justification": justification,
            "timestamp": _now_iso(),
        })
        self._write_story(story)
        self._audit(issue_id, voter, "poker_vote",
                    points=points, justification_len=len(justification))
        return story

    def set_points(self, issue_id: str, points: int, actor: str) -> Story:
        story = self.read(issue_id)
        story.points = points
        self._write_story(story)
        self._audit(issue_id, actor, "set_points", points=points)
        return story

    def increment_refinement_round(self, issue_id: str) -> Story:
        story = self.read(issue_id)
        story.refinement_rounds += 1
        self._write_story(story)
        self._audit(issue_id, "system", "refinement_round",
                    round=story.refinement_rounds)
        return story

    # ── Work bits ────────────────────────────────────────────────────────

    def assign(self, issue_id: str, worker: str) -> Story:
        story = self.read(issue_id)
        if story.assignee and story.assignee != worker:
            raise BoardError(
                f"story {issue_id} already assigned to {story.assignee!r}"
            )
        story.assignee = worker
        self._write_story(story)
        self._audit(issue_id, worker, "assign")
        return story

    def unassign(self, issue_id: str) -> Story:
        story = self.read(issue_id)
        prev = story.assignee
        story.assignee = ""
        self._write_story(story)
        self._audit(issue_id, prev or "system", "unassign")
        return story

    def set_commit(self, issue_id: str, commit_sha: str, actor: str) -> Story:
        story = self.read(issue_id)
        story.commit_sha = commit_sha
        self._write_story(story)
        self._audit(issue_id, actor, "set_commit", commit_sha=commit_sha)
        return story

    def set_wiki_touched(self, issue_id: str, actor: str,
                          value: bool = True) -> Story:
        story = self.read(issue_id)
        story.wiki_touched = value
        self._write_story(story)
        self._audit(issue_id, actor, "wiki_touched", value=value)
        return story

    # ── Counters (for mode-switch logic) ─────────────────────────────────

    def count_state(self, state: str) -> int:
        return sum(1 for meta in self._read_index().values()
                   if meta.get("state") == state)

    def counts_by_state(self) -> dict[str, int]:
        idx = self._read_index()
        out = {s: 0 for s in VALID_STATES}
        for meta in idx.values():
            s = meta.get("state", "")
            if s in out:
                out[s] += 1
        return out


def new_issue_id(prefix: str = "S") -> str:
    """Convenience: generate a short unique issue_id."""
    return f"{prefix}-{uuid.uuid4().hex[:6]}"

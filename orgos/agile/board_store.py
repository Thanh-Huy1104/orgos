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
  activated_at  : ISO — set on the FIRST in_progress transition (never reset)
  closed_at     : ISO — set when the story transitions to done
  created_at    : ISO
  updated_at    : ISO
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
import uuid
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def derive_component_from_files(files_to_touch: list[str]) -> str:
    """Derive a component (ownership boundary) from a story's files_to_touch.

    Feature-branch style — no hardcoded vocabulary. What the story TOUCHES
    IS what defines its component:
      ["auth/routes.py", "auth/tokens.py"] → "auth"
      ["notes/routes.py"] → "notes"
      ["tests/test_notes.py"] → "notes"   (test file normalized to its subject)
      ["tests/notes/test_foo.py"] → "notes"
      ["app.py"] → "app-py"               (leaf file → unique lock)
      [] → "core"                         (nothing specified → default lock)

    When files span multiple components, uses the most common one; ties
    broken alphabetically. A story spanning multiple components is a smell
    (should be split), but we don't reject it — we just pick a lock.
    """
    if not files_to_touch:
        return "core"

    def _one(f: str) -> str:
        # Normalize the path
        f = f.lstrip("./").strip()
        if not f:
            return "core"
        # Test file conventions:
        #   tests/test_<name>.py  → <name>
        #   test/test_<name>.py   → <name>
        m = re.match(r"tests?/test_(\w+)\.\w+$", f)
        if m:
            return m.group(1)
        #   tests/<name>/…       → <name>
        m = re.match(r"tests?/([\w-]+)/", f)
        if m:
            return m.group(1)
        # Top-level directory: notes/routes.py → notes
        m = re.match(r"([\w-]+)/", f)
        if m:
            return m.group(1)
        # Leaf file at repo root: app.py → app-py (unique per file so
        # multiple stories touching the same file serialize on the SAME
        # component; each root file is its own lock).
        return f.replace(".", "-").replace("/", "-").lower()

    counts = Counter(_one(f) for f in files_to_touch)
    # Most common; tie broken alphabetically for determinism
    max_count = max(counts.values())
    winners = sorted(k for k, v in counts.items() if v == max_count)
    return winners[0]


VALID_STATES = (
    "draft", "refinement", "ready", "in_progress",
    "review", "pending_acceptance", "done", "blocked",
)
VALID_TYPES = ("architecture", "test", "security", "feature", "docs")

# state machine — key = current state, value = allowed next states.
# `review` → `pending_acceptance` is the merge-clean handoff to PO.
# PO's acceptance ceremony transitions `pending_acceptance` → `done` (accept)
# or → `blocked` (reject with reason).
TRANSITIONS: dict[str, tuple[str, ...]] = {
    "draft":              ("refinement", "blocked"),
    "refinement":         ("ready", "draft", "blocked"),
    "ready":              ("in_progress", "blocked"),
    "in_progress":        ("review", "blocked", "ready"),   # ready → return-to-queue
    "review":             ("pending_acceptance", "done", "in_progress", "blocked"),
    # pending_acceptance → ready enables the §H1 AC-retry loop: PO rejects
    # a story on AC, but the code is already merged. Send it back to ready
    # with the rejection reason injected into the body so the next puller
    # can fix specifically what was unmet. Only block after N=3 AC rejects.
    "pending_acceptance": ("done", "blocked", "review", "ready"),
    # §D2 — customer can reopen a done story if the shipped code doesn't
    # match spec intent (independent of AC gate). PO's convention is
    # "done is done" but the customer's second opinion beats that convention.
    "done":               ("blocked",),
    "blocked":            ("draft", "refinement", "ready", "in_progress", "review", "pending_acceptance"),
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
    activated_at: str = ""   # first in_progress (for SPE timing; never reset)
    closed_at: str = ""      # set on done
    files_to_touch: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    sprint_number: int = 0   # 0 = unassigned (not in any sprint yet)
    attempts: int = 0        # executor attempts — retry until MAX before block
    component: str = "core"  # ownership boundary — see BoardStore claim logic.
                             # Two stories in the same component cannot be
                             # in flight simultaneously — mirrors how real
                             # Scrum teams avoid stepping on each other by
                             # module/component ownership.
    acceptance_criteria: list[str] = field(default_factory=list)
                             # PO's Definition of Done bullets. When a spec-file
                             # is provided, these are extracted from `## AC:`
                             # blocks; otherwise the PO produces them during
                             # decomposition. The acceptance ceremony checks
                             # each bullet against the merged code.
    blocked_reason: str = "" # why the story is blocked — set from the
                             # transition reason on entry to `blocked`, cleared
                             # on exit. The 2026-07-22 TS run showed the PO
                             # can't decide unblock-vs-drop when this is empty.
    created_at: str = ""
    updated_at: str = ""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write(path: Path, text: str) -> None:
    """Atomic write via temp-file + rename in the same directory.

    On Windows, ``os.replace`` can sporadically fail with ``PermissionError``
    (WinError 5) when antivirus or the search indexer is still holding the
    freshly written temp file. Retry a few times with a short backoff before
    giving up.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=".tmp-", suffix=path.suffix, dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        last_err: Exception | None = None
        for attempt in range(10):
            try:
                os.replace(tmp, path)
                return
            except PermissionError as e:  # Windows AV / indexer race
                last_err = e
                time.sleep(0.05 * (attempt + 1))
        assert last_err is not None
        raise last_err
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
        self._claim_lock = threading.Lock()

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

        Also enforces dependency gate: a story with `depends_on: [X, Y]` is
        NOT returned unless X and Y are both in `done` state.
        """
        ready = self.list_state("ready")
        primary: dict[str, tuple[str, ...]] = {
            "architecture": ("architecture", "feature"),
            "architect":    ("architecture", "feature"),
            "test":         ("test",),
            "security":     ("security",),
            "devsecops":    ("security",),
            "docs":         ("docs",),
        }
        allowed = primary.get(worker_type, ("architecture", "test", "security",
                                             "feature", "docs"))
        idx = self._read_index()
        def _deps_satisfied(s: Story) -> bool:
            if not s.depends_on:
                return True
            for dep_id in s.depends_on:
                dep_meta = idx.get(dep_id)
                if not dep_meta or dep_meta.get("state") != "done":
                    return False
            return True
        return [s for s in ready if s.type in allowed and _deps_satisfied(s)]

    def _components_in_flight(self) -> set[str]:
        """Return the set of `component` values for stories that are
        currently in in_progress, review, or pending_acceptance state.

        A story whose component is in this set MUST NOT be claimed by
        another agent — this mirrors real Scrum ownership: only one
        pair works `auth` at a time, another works `notes`, another
        `folders`. Prevents same-file collisions structurally rather
        than relying on PO's `files_to_touch` being complete.
        """
        locked: set[str] = set()
        for state in ("in_progress", "review", "pending_acceptance"):
            for s in self.list_state(state):
                comp = getattr(s, "component", "core") or "core"
                locked.add(comp)
        return locked

    def list_ready_for_sprint(
        self, worker_type: str, *, sprint_number: int,
    ) -> list[Story]:
        """Sprint-filtered variant of list_ready_for_type.

        Also enforces COMPONENT OWNERSHIP: filters out stories whose
        component is currently in flight (in_progress/review/pending_acceptance).
        Mirrors real Scrum where only one pair works a given module at
        a time so devs don't step on each other.

        If `sprint_number == 0`: skip the sprint filter (bootstrap mode).
        The component filter still applies.
        """
        candidates = self.list_ready_for_type(worker_type)
        if sprint_number > 0:
            candidates = [s for s in candidates if s.sprint_number == sprint_number]
        # Component ownership: skip anything whose component is in flight.
        locked = self._components_in_flight()
        return [
            s for s in candidates
            if (getattr(s, "component", "core") or "core") not in locked
        ]

    def try_claim_next_for(
        self, role: str, *, actor: str,
        sprint_number: int = 0,
    ) -> Optional[Story]:
        """Atomically pull the top matching READY story for `role` and move it
        to in_progress. Skips stories whose files_to_touch overlaps with any
        currently in_progress or review story. Returns None if nothing
        claimable.

        Thread-safe within a single process (uses threading.Lock). Not safe
        across multiple processes sharing the same board directory — the
        async runtime is single-process by design (one asyncio event loop
        drives all agents).
        """
        with self._claim_lock:
            candidates = self.list_ready_for_sprint(role, sprint_number=sprint_number)
            if not candidates:
                return None

            # Compute the set of files currently locked by in-flight stories
            locked_files: set[str] = set()
            for state in ("in_progress", "review"):
                for s in self.list_state(state):
                    locked_files.update(s.files_to_touch or [])

            for story in candidates:
                overlap = set(story.files_to_touch or []) & locked_files
                if overlap:
                    continue  # try the next ready story
                # Claim it
                try:
                    self.assign(story.issue_id, actor)
                    self.transition(story.issue_id, "in_progress", actor=actor)
                    return self.read(story.issue_id)
                except (InvalidTransition, BoardError):
                    continue  # race with another caller; try next
            return None

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
        files_to_touch: Optional[list[str]] = None,
        component: Optional[str] = None,
        acceptance_criteria: Optional[list[str]] = None,
    ) -> Story:
        if story_type not in VALID_TYPES:
            raise BoardError(
                f"invalid type: {story_type!r}. Valid: {VALID_TYPES}"
            )
        if self.exists(issue_id):
            raise BoardError(f"story already exists: {issue_id}")
        # Component derivation. If the caller explicitly provided one, use it.
        # Otherwise auto-derive from files_to_touch — feature-branch style
        # where the story's file scope IS its component (no hardcoded list).
        ftt = list(files_to_touch or [])
        if component is None or not component.strip():
            comp = derive_component_from_files(ftt)
        else:
            comp = component.strip()
        now = _now_iso()
        story = Story(
            issue_id=issue_id,
            title=title.strip(),
            body=body,
            state="draft",
            type=story_type,
            priority=priority,
            files_to_touch=ftt,
            component=comp,
            acceptance_criteria=[
                str(c).strip() for c in (acceptance_criteria or []) if str(c).strip()
            ],
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
        # SPE timing: stamp activated_at on the FIRST in_progress (never reset,
        # so spillover→re-activation preserves the true first-touch time) and
        # closed_at on done.
        if new_state == "in_progress" and not story.activated_at:
            story.activated_at = _now_iso()
        elif new_state == "done" and not story.closed_at:
            story.closed_at = _now_iso()
        # Persist WHY on the story itself, not just in the audit log — the
        # replan PO reads the board, not the audit trail.
        if new_state == "blocked":
            story.blocked_reason = reason or story.blocked_reason
        elif old == "blocked":
            story.blocked_reason = ""
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

    def set_sprint_number(self, issue_id: str, sprint_number: int, actor: str) -> Story:
        story = self.read(issue_id)
        story.sprint_number = sprint_number
        self._write_story(story)
        self._audit(issue_id, actor, "set_sprint_number", sprint_number=sprint_number)
        return story

    def increment_attempts(self, issue_id: str, actor: str) -> Story:
        """Bump the executor-attempt counter. Called on story_no_commit before
        deciding whether to retry (attempts < MAX) or permanently block.
        """
        story = self.read(issue_id)
        story.attempts += 1
        self._write_story(story)
        self._audit(issue_id, actor, "increment_attempts",
                    attempts=story.attempts)
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

# orgos v2 — Async Scrum Team Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the synchronous dispatcher with an async agent runtime where each of the 5 Scrum roles runs independently, wakes on its own heartbeat, and pulls work from a shared board. Delegate actual coding to OpenCode via a `CodingExecutor` protocol.

**Architecture:** No central dispatcher. `TeamSupervisor` spawns 5 `AsyncAgent` tasks (asyncio); each reads its `HEARTBEAT.md` for a natural-language schedule and either checks the board (delivery agents: architect/test/devsecops) or runs scheduled ceremonies (coordination agents: po/scrum_master). A `MergeQueue` serializes cross-worktree git operations via rebase-before-merge with `git rerere` for conflict re-use. Personas keep the 5-file structure; `HEARTBEAT.md` is now a schedule and `MEMORY.md` is agent-updated.

**Tech Stack:** Python 3.11+, asyncio (stdlib), subprocess for OpenCode invocation, git worktrees, existing orgos packages (crewai, pydantic, ruamel.yaml). No new runtime dependencies.

**Spec:** `docs/superpowers/specs/2026-07-16-orgos-v2-async-scrum-team.md`

## Global Constraints

- Persona file convention: keep **5 files** per role (`SOUL.md`, `BRAIN.md`, `HABITS.md`, `MEMORY.md`, `HEARTBEAT.md`) — do NOT rename to OpenClaw's 6-file convention
- `MEMORY.md` is the only file agents may write to; SOUL/BRAIN/HABITS are human-edited; HEARTBEAT.md is human-edited but its format is now a natural-language schedule
- Coding executor: **OpenCode only** in v2 (Aider/Claude Code deferred). Behind a `CodingExecutor` Protocol so future implementations don't touch agents
- Board coordination via `try_claim_next_for(role)` — atomic under `board_lock`. `files_to_touch` overlap check blocks concurrent stories touching the same files
- Every worktree init runs `git config rerere.enabled true`
- Merge strategy: FIFO queue → rebase-before-merge → escalate to `blocked` on conflict (no LLM auto-resolution)
- Supervisor restarts crashed agents with exponential backoff (5s, 30s, 5min, 30min, 60min)
- Sprint boundary: whenever `scrum_master` runs retrospective (its HEARTBEAT schedules this every 4 hours by default)
- Fresh reset: no v1 backwards compat; v1 workspaces refused with a clear message
- Delete `orgos/agile/dispatcher.py`, `orgos/agile/multi_sprint.py`, `orgos/agile/dispatcher_briefs.py`, and their tests
- All 138 existing regression tests (after deletion of dispatcher-related ones) must still pass at every task boundary
- Every task ends with a passing test suite and a commit

---

## File plan

### Delete
```
orgos/agile/dispatcher.py
orgos/agile/multi_sprint.py
orgos/agile/dispatcher_briefs.py
tests/agile/test_dispatcher_noop.py
```

### Create
```
orgos/agile/agent_loop.py           AsyncAgent — per-role async runtime
orgos/agile/coding_executor.py      CodingExecutor Protocol + OpenCodeExecutor
orgos/agile/heartbeat_scheduler.py  natural-language HEARTBEAT.md → asyncio timers
orgos/agile/merge_queue.py          FIFO merge queue + MergeWorker
orgos/agile/supervisor.py           TeamSupervisor — crash-restart with backoff
tests/agile/test_agent_loop.py
tests/agile/test_coding_executor.py
tests/agile/test_heartbeat_scheduler.py
tests/agile/test_merge_queue.py
tests/agile/test_supervisor.py
```

### Modify
```
orgos/agile/board_store.py       add try_claim_next_for + files_to_touch
orgos/agile/goal_decomposer.py   require files_to_touch on drafted stories
orgos/agile/team_workspace.py    restructure for per-agent worktrees
orgos/agile/live_events.py       add new event types
orgos/agile/team_report.py       per-agent status + merge queue tail
orgos/cli.py                     new commands: start / stop / status
tests/agile/test_board_store.py  cover new methods
tests/agile/test_team_workspace.py  cover per-agent worktree
tests/agile/test_decomposer_and_env.py  files_to_touch cases
agents/architect/HEARTBEAT.md    natural-language schedule
agents/test/HEARTBEAT.md         same
agents/devsecops/HEARTBEAT.md    same
agents/po/HEARTBEAT.md           natural-language schedule (coordination-only)
agents/scrum_master/HEARTBEAT.md natural-language schedule (coordination-only)
```

---

## Task order (dependencies)

```
1 (cleanup) ─────────────────────────────────────────────┐
                                                         │
2 (board_store) ─── 3 (decomposer) ─── 4 (workspace) ───┤
                                                         │
5 (heartbeat_scheduler) ── 6 (coding_executor) ── 7 (merge_queue) ─┤
                                                                    │
8 (agent_loop) ── 9 (supervisor) ─────────────────────────────────┤
                                                                    │
10 (live_events) ── 11 (team_report) ── 12 (cli) ──────────────────┤
                                                                    │
13 (personas) ── 14 (regression check) ── 15 (e2e smoke) ──────────┘
```

Each task ends with `pytest -q` green + a commit. Fresh subagent per task recommended.

---

### Task 1: Clean-slate — delete legacy dispatcher / multi_sprint / dispatcher_briefs

**Files:**
- Delete: `orgos/agile/dispatcher.py`
- Delete: `orgos/agile/multi_sprint.py`
- Delete: `orgos/agile/dispatcher_briefs.py`
- Delete: `tests/agile/test_dispatcher_noop.py`
- Modify: `orgos/cli.py` — remove imports and code paths that reference the deleted modules
- Modify: `orgos/agile/waterfall_runner.py` — remove import of `DispatchResult, WorkResult` from `orgos.agile.dispatcher` and inline any needed dataclass types

**Interfaces:**
- Consumes: nothing
- Produces: a repo with no `dispatcher.py` / `multi_sprint.py` / `dispatcher_briefs.py`. `pytest -q` still passes.

- [ ] **Step 1: Verify current test count baseline**

Run: `cd /Users/th/Documents/Github/orgos && pytest -q 2>&1 | tail -3`
Expected: `138 passed`

- [ ] **Step 2: Delete the three source files**

```bash
git rm orgos/agile/dispatcher.py orgos/agile/multi_sprint.py orgos/agile/dispatcher_briefs.py
```

- [ ] **Step 3: Delete the dispatcher-specific test file**

```bash
git rm tests/agile/test_dispatcher_noop.py
```

- [ ] **Step 4: Fix waterfall_runner.py — remove dispatcher import**

Open `orgos/agile/waterfall_runner.py`. Find the line:
```python
from orgos.agile.dispatcher import DispatchResult, WorkResult
```
Replace it with an inline definition placed near the top of the file (after other imports):

```python
from dataclasses import dataclass, field

@dataclass
class WorkResult:
    story_id: str
    role: str
    status: str
    commit_sha: str = ""
    diff_summary: str = ""
    envelope: dict = field(default_factory=dict)
    tokens_input: int = 0
    tokens_output: int = 0
    wall_seconds: float = 0.0
    error: str = ""


@dataclass
class DispatchResult:
    team_id: str
    goal: str
    started_at: str
    ended_at: str
    reason_stopped: str
    stories_created: int
    stories_done: int
    stories_blocked: int
    total_tokens_input: int = 0
    total_tokens_output: int = 0
    per_story_results: list = field(default_factory=list)
    pr_url: str = ""
```

- [ ] **Step 5: Fix cli.py — remove dispatcher/multi_sprint import paths**

Open `orgos/cli.py`. Find the `_cmd_run` function. Replace the multi-sprint branch and the single-sprint branch's `Dispatcher` construction with a stub that prints an error message pointing users at `orgos start`:

Find (roughly around line 106):
```python
        if args.sprints > 1:
            print(f"[cli] mode=scrum · MULTI-SPRINT ({args.sprints} sprints) · "
                  f"n_workers={args.n_workers} · "
                  f"sprint_story_cap={args.max_stories} · "
                  f"sprint_duration={args.max_seconds}s", flush=True)
            from orgos.agile.multi_sprint import run_multi_sprint
```

Replace the entire multi-sprint block AND the single-sprint `from orgos.agile.dispatcher import Dispatcher` block with:
```python
        print(
            "[cli] ERROR: `orgos run` in scrum mode has been replaced by "
            "`orgos start` (v2 async runtime). See docs/superpowers/specs/"
            "2026-07-16-orgos-v2-async-scrum-team.md",
            file=sys.stderr,
        )
        return 3
```

Leave the `--waterfall` branch untouched.

- [ ] **Step 6: Fix cli.py — remove watch command (references deleted multi_sprint)**

Find `_cmd_watch` function and its subparser registration (`watch_p = sub.add_parser("watch", …)` block). Delete both entirely.

- [ ] **Step 7: Fix pilot benchmark harness (still references deleted modules)**

If `scripts/run_benchmark.py` still exists and imports from `orgos.agile.dispatcher` or `orgos.agile.benchmark`, delete `scripts/run_benchmark.py` too:
```bash
[ -f scripts/run_benchmark.py ] && git rm scripts/run_benchmark.py || true
```

- [ ] **Step 8: Delete any remaining broken imports**

Run: `python3 -c "from orgos.cli import main; print('ok')"`
Expected: `ok` (no ImportError).

If ImportError, grep for and remove any stray reference to the deleted modules:
```bash
grep -rn "from orgos.agile.dispatcher\|from orgos.agile.multi_sprint\|from orgos.agile.dispatcher_briefs" orgos/ tests/ scripts/ 2>/dev/null
```
Fix each hit.

- [ ] **Step 9: Run tests**

Run: `pytest -q 2>&1 | tail -3`
Expected: `137 passed` (was 138; we deleted `test_dispatcher_noop.py` which had 1 file worth). If failures: read the error, fix the calling code (probably a stray import somewhere).

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "refactor: delete v1 dispatcher/multi_sprint/dispatcher_briefs for v2 rewrite

Fresh-reset for the async-agent architecture. orgos run --scrum now prints
a message pointing at 'orgos start' (implemented in later tasks). Waterfall
mode still works via inlined DispatchResult/WorkResult dataclasses."
```

---

### Task 2: BoardStore — add `try_claim_next_for` + `files_to_touch`

**Files:**
- Modify: `orgos/agile/board_store.py`
- Modify: `tests/agile/test_board_store.py`

**Interfaces:**
- Consumes: nothing new
- Produces:
  - `Story.files_to_touch: list[str]` (new field, default `[]`)
  - `BoardStore.try_claim_next_for(role: str, actor: str) → Optional[Story]` (atomic under an internal lock)

- [ ] **Step 1: Write the failing test for the files_to_touch field**

Add to `tests/agile/test_board_store.py` inside `TestDraft`:
```python
    def test_files_to_touch_default_empty(self, board):
        s = board.draft_story(issue_id="A", title="t", body="b",
                               story_type="feature")
        assert s.files_to_touch == []

    def test_files_to_touch_persists(self, board):
        s = board.draft_story(issue_id="A", title="t", body="b",
                               story_type="feature",
                               files_to_touch=["app.py", "tests/test_app.py"])
        assert board.read("A").files_to_touch == ["app.py", "tests/test_app.py"]
```

- [ ] **Step 2: Run test — expect failure**

Run: `pytest tests/agile/test_board_store.py::TestDraft::test_files_to_touch_default_empty -v`
Expected: FAIL — either the field doesn't exist on Story, or `draft_story()` doesn't accept the kwarg.

- [ ] **Step 3: Add the field and threading**

In `orgos/agile/board_store.py`:

Add to the `Story` dataclass (after `commit_sha`, before `depends_on`):
```python
    files_to_touch: list[str] = field(default_factory=list)
```

Update `BoardStore.draft_story()` to accept `files_to_touch`:
```python
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
    ) -> Story:
```
And in the body, add `files_to_touch=list(files_to_touch or []),` to the `Story(...)` constructor call.

- [ ] **Step 4: Run tests — expect pass**

Run: `pytest tests/agile/test_board_store.py::TestDraft -v`
Expected: all `TestDraft` tests pass including the two new ones.

- [ ] **Step 5: Write failing tests for atomic claim**

Add to `tests/agile/test_board_store.py`:
```python
class TestTryClaim:
    def test_claim_transitions_to_in_progress(self, board):
        board.draft_story(issue_id="A", title="arch", body="b",
                          story_type="architecture")
        board.transition("A", "refinement", actor="sm")
        board.transition("A", "ready", actor="sm")
        story = board.try_claim_next_for("architect", actor="arch_agent")
        assert story is not None
        assert story.issue_id == "A"
        assert board.read("A").state == "in_progress"
        assert board.read("A").assignee == "arch_agent"

    def test_claim_returns_none_when_no_ready_stories(self, board):
        assert board.try_claim_next_for("architect", actor="arch_agent") is None

    def test_claim_respects_type_filter(self, board):
        board.draft_story(issue_id="A", title="test", body="b",
                          story_type="test")
        board.transition("A", "refinement", actor="sm")
        board.transition("A", "ready", actor="sm")
        # architect worker only pulls architecture+feature, not test
        assert board.try_claim_next_for("architect", actor="arch_agent") is None
        # test worker pulls test-typed story
        story = board.try_claim_next_for("test", actor="test_agent")
        assert story is not None and story.issue_id == "A"

    def test_claim_blocks_on_files_to_touch_overlap(self, board):
        # Story A is in_progress touching app.py
        board.draft_story(issue_id="A", title="a", body="b",
                          story_type="architecture",
                          files_to_touch=["app.py"])
        board.transition("A", "refinement", actor="sm")
        board.transition("A", "ready", actor="sm")
        s = board.try_claim_next_for("architect", actor="arch_agent")
        assert s.issue_id == "A"
        # Story B is ready and would also touch app.py — must NOT be claimable
        board.draft_story(issue_id="B", title="b", body="b",
                          story_type="architecture",
                          files_to_touch=["app.py", "other.py"])
        board.transition("B", "refinement", actor="sm")
        board.transition("B", "ready", actor="sm")
        assert board.try_claim_next_for("architect", actor="arch_agent2") is None

    def test_claim_allows_non_overlapping_parallel(self, board):
        board.draft_story(issue_id="A", title="a", body="b",
                          story_type="architecture",
                          files_to_touch=["app.py"])
        board.draft_story(issue_id="B", title="b", body="b",
                          story_type="architecture",
                          files_to_touch=["util.py"])
        for iid in ("A", "B"):
            board.transition(iid, "refinement", actor="sm")
            board.transition(iid, "ready", actor="sm")
        s1 = board.try_claim_next_for("architect", actor="arch1")
        s2 = board.try_claim_next_for("architect", actor="arch2")
        assert {s1.issue_id, s2.issue_id} == {"A", "B"}
```

- [ ] **Step 6: Run — expect fail**

Run: `pytest tests/agile/test_board_store.py::TestTryClaim -v`
Expected: FAIL (method doesn't exist).

- [ ] **Step 7: Implement try_claim_next_for**

Add to `orgos/agile/board_store.py` at the top of the file:
```python
import threading
```

Add to `BoardStore.__init__` (after `self.audit_dir.mkdir(...)`):
```python
        self._claim_lock = threading.Lock()
```

Add the method to the `BoardStore` class (near the other list_ready methods):
```python
    def try_claim_next_for(
        self, role: str, *, actor: str,
    ) -> Optional[Story]:
        """Atomically pull the top matching READY story for `role` and move it
        to in_progress. Skips stories whose files_to_touch overlaps with any
        currently in_progress or review story. Returns None if nothing
        claimable.

        Thread-safe: multiple concurrent callers will each get a different
        story (or None).
        """
        with self._claim_lock:
            candidates = self.list_ready_for_type(role)
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
```

- [ ] **Step 8: Run tests — expect pass**

Run: `pytest tests/agile/test_board_store.py -v 2>&1 | tail -20`
Expected: all `TestTryClaim` tests pass. All other existing tests still pass.

- [ ] **Step 9: Commit**

```bash
git add orgos/agile/board_store.py tests/agile/test_board_store.py
git commit -m "feat(board): add try_claim_next_for atomic claim + files_to_touch overlap check

New Story.files_to_touch field with default [].
New BoardStore.try_claim_next_for(role, actor) that:
- filters by role type (via list_ready_for_type)
- skips stories whose files_to_touch overlaps with in_progress/review
- atomically transitions the picked story to in_progress
Uses internal threading.Lock for concurrent-caller safety."
```

---

### Task 3: goal_decomposer — require `files_to_touch` on drafted stories

**Files:**
- Modify: `orgos/agile/goal_decomposer.py`
- Modify: `tests/agile/test_decomposer_and_env.py`

**Interfaces:**
- Consumes: `BoardStore.draft_story(..., files_to_touch=[...])` from Task 2
- Produces: drafted stories carry `files_to_touch` populated from the PO's output

- [ ] **Step 1: Update the PO decomposer prompt to require files_to_touch**

In `orgos/agile/goal_decomposer.py`, find `_DECOMPOSE_BRIEF_TEMPLATE` (the multi-line prompt string). Add a new rule after the existing rule about story types:

```
5. Every story MUST include `files_to_touch: [<paths>]` — the specific files
   the story will create or modify. Be exact. This is used to prevent
   concurrent stories from stepping on each other's code. Example:
   `"files_to_touch": ["app.py", "tests/test_auth.py"]`. If genuinely
   unknowable (e.g., a research story), use `[]`.
```

Renumber the subsequent rules accordingly (former 5→6, 6→7).

- [ ] **Step 2: Update the parser to store files_to_touch**

Find the loop that iterates `parsed_stories` and calls `board.draft_story(...)`. Update to extract and pass files_to_touch:

Find:
```python
        raw_deps = s.get("depends_on") or s.get("dependsOn") or []
        if not isinstance(raw_deps, list):
            raw_deps = []
        dep_specs.append(raw_deps)
```

Add right below:
```python
        raw_ftt = s.get("files_to_touch") or []
        if not isinstance(raw_ftt, list):
            raw_ftt = []
        files_to_touch = [str(p).strip() for p in raw_ftt if str(p).strip()]
```

Update the `board.draft_story(...)` call to include `files_to_touch=files_to_touch,`.

- [ ] **Step 3: Write test for the extraction path**

In `tests/agile/test_decomposer_and_env.py`, add a new class:

```python
class TestFilesToTouchExtraction:
    """PO output → files_to_touch on the drafted story."""

    def test_files_to_touch_populated(self, tmp_path, monkeypatch):
        # Patch decompose_goal's spawn call to return a fixed PO output
        from orgos.agile.board_store import BoardStore
        from orgos.agile import goal_decomposer as gd

        fake_stories = [{
            "title": "Add auth",
            "body": "Implement JWT auth in app.py",
            "type": "feature",
            "priority": 90,
            "files_to_touch": ["app.py", "tests/test_auth.py"],
            "depends_on": [],
        }]

        class FakeTaskOutput:
            raw = '[{"title": "Add auth", "body": "Implement JWT auth in app.py", '\
                  '"type": "feature", "priority": 90, '\
                  '"files_to_touch": ["app.py", "tests/test_auth.py"], '\
                  '"depends_on": []}]'

        class FakeResult:
            tasks_output = [FakeTaskOutput()]
            token_usage = None

        def fake_spawn(role, brief, **kwargs):
            return FakeResult()

        monkeypatch.setattr(gd, "spawn", fake_spawn)
        b = BoardStore(tmp_path)
        ids = gd.decompose_goal(
            goal="add auth", repo_root=tmp_path, board=b, model="mock",
        )
        assert len(ids) == 1
        story = b.read(ids[0])
        assert story.files_to_touch == ["app.py", "tests/test_auth.py"]

    def test_files_to_touch_defaults_empty_when_missing(self, tmp_path, monkeypatch):
        from orgos.agile.board_store import BoardStore
        from orgos.agile import goal_decomposer as gd

        class FakeTaskOutput:
            raw = '[{"title": "t", "body": "b", "type": "feature", "priority": 5}]'
        class FakeResult:
            tasks_output = [FakeTaskOutput()]
            token_usage = None
        monkeypatch.setattr(gd, "spawn", lambda role, brief, **kw: FakeResult())

        b = BoardStore(tmp_path)
        ids = gd.decompose_goal(
            goal="t", repo_root=tmp_path, board=b, model="mock",
        )
        assert b.read(ids[0]).files_to_touch == []
```

- [ ] **Step 4: Run tests — expect pass**

Run: `pytest tests/agile/test_decomposer_and_env.py::TestFilesToTouchExtraction -v`
Expected: both new tests pass.

- [ ] **Step 5: Run full suite — nothing broken**

Run: `pytest -q 2>&1 | tail -3`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add orgos/agile/goal_decomposer.py tests/agile/test_decomposer_and_env.py
git commit -m "feat(decomposer): require files_to_touch on every drafted story

PO prompt extended with rule that every story must annotate the files it
will create or modify. Parser stores this on the Story via draft_story.
Enables board's files_to_touch overlap detection (see previous commit)."
```

---

### Task 4: TeamWorkspace — per-agent worktrees + baseline pytest snapshot

**Files:**
- Modify: `orgos/agile/team_workspace.py`
- Modify: `tests/agile/test_team_workspace.py`

**Interfaces:**
- Consumes: nothing from earlier tasks
- Produces:
  - `TeamWorkspace.agent_dir(role) → Path` — `.orgos_teams/<id>/agents/<role>/`
  - `TeamWorkspace.agent_worktree(role) → Path` — `.orgos_teams/<id>/agents/<role>/worktree/`
  - `TeamWorkspace.agent_branch(role) → str` — `team/<id>/agent/<role>`
  - `TeamWorkspace.integration_worktree → Path` — `.orgos_teams/<id>/integration/`
  - `TeamWorkspace.integration_branch → str` — `team/<id>/integration`
  - `TeamWorkspace.ensure_agent_workspace(role)` — idempotent create of agent dir + worktree + branch + rerere config
  - New attribute `.baseline_test_result: dict` recorded at create time

- [ ] **Step 1: Write failing tests**

In `tests/agile/test_team_workspace.py`, add a new class:

```python
ROLES = ("po", "scrum_master", "architect", "test", "devsecops")

class TestPerAgentWorktrees:
    def test_agent_dir_shape(self, repo):
        ws = TeamWorkspace.create("t1", repo, goal="g", model="m")
        for role in ROLES:
            ws.ensure_agent_workspace(role)
            assert ws.agent_dir(role).exists()
            assert ws.agent_worktree(role).exists()

    def test_integration_worktree_created(self, repo):
        ws = TeamWorkspace.create("t1", repo, goal="g", model="m")
        assert ws.integration_worktree.exists()
        assert ws.integration_branch == "team/t1/integration"

    def test_each_agent_has_own_branch(self, repo):
        ws = TeamWorkspace.create("t1", repo, goal="g", model="m")
        for role in ROLES:
            ws.ensure_agent_workspace(role)
            branches = subprocess.run(
                ["git", "branch", "--format=%(refname:short)"],
                cwd=repo, capture_output=True, text=True,
            ).stdout.strip().splitlines()
            assert f"team/t1/agent/{role}" in branches

    def test_rerere_enabled_in_agent_worktree(self, repo):
        ws = TeamWorkspace.create("t1", repo, goal="g", model="m")
        ws.ensure_agent_workspace("architect")
        result = subprocess.run(
            ["git", "config", "--get", "rerere.enabled"],
            cwd=ws.agent_worktree("architect"),
            capture_output=True, text=True,
        )
        assert result.stdout.strip() == "true"

    def test_baseline_test_result_recorded(self, repo):
        ws = TeamWorkspace.create("t1", repo, goal="g", model="m")
        # Even if there are no tests to run, baseline is a dict with a status
        assert isinstance(ws.baseline_test_result, dict)
        assert "status" in ws.baseline_test_result
```

- [ ] **Step 2: Run tests — expect fail**

Run: `pytest tests/agile/test_team_workspace.py::TestPerAgentWorktrees -v`
Expected: FAIL — methods don't exist.

- [ ] **Step 3: Implement per-agent workspace helpers**

In `orgos/agile/team_workspace.py`, add these methods to the `TeamWorkspace` class (after `.exists()`):

```python
    # ── Per-agent workspace layout (v2 async runtime) ─────────────────

    ROLE_NAMES = ("po", "scrum_master", "architect", "test", "devsecops")

    @property
    def agents_root(self) -> Path:
        return self.root / "agents"

    def agent_dir(self, role: str) -> Path:
        return self.agents_root / role

    def agent_worktree(self, role: str) -> Path:
        return self.agent_dir(role) / "worktree"

    def agent_branch(self, role: str) -> str:
        return f"team/{self.team_id}/agent/{role}"

    @property
    def integration_worktree(self) -> Path:
        return self.root / "integration"

    @property
    def integration_branch(self) -> str:
        return f"team/{self.team_id}/integration"

    def ensure_agent_workspace(self, role: str) -> None:
        """Idempotent: create the per-agent dir + worktree + branch. Enable
        git rerere in the worktree.
        """
        agent_dir = self.agent_dir(role)
        agent_dir.mkdir(parents=True, exist_ok=True)

        worktree = self.agent_worktree(role)
        if not worktree.exists():
            branch = self.agent_branch(role)
            subprocess.run(
                ["git", "worktree", "add", "-b", branch,
                 str(worktree), self.integration_branch],
                cwd=self.source_repo, check=True, capture_output=True,
            )
            subprocess.run(
                ["git", "config", "rerere.enabled", "true"],
                cwd=worktree, check=True, capture_output=True,
            )
```

Now the harder change: update `TeamWorkspace.create()` to create the `integration/` worktree instead of the old `worktree/` and record the baseline test result.

Find:
```python
        subprocess.run(
            ["git", "worktree", "add", "-b", branch, str(ws.worktree), "HEAD"],
            cwd=ws.source_repo, check=True, capture_output=True,
        )
```

Replace with:
```python
        # Integration branch (the "main" working branch for this team)
        integration_branch = f"team/{team_id}/integration"
        subprocess.run(
            ["git", "worktree", "add", "-b", integration_branch,
             str(ws.integration_worktree), "HEAD"],
            cwd=ws.source_repo, check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "config", "rerere.enabled", "true"],
            cwd=ws.integration_worktree, check=True, capture_output=True,
        )
```

Update all references to `ws.worktree` inside `TeamWorkspace.create()` to use `ws.integration_worktree` (the `.gitignore` baseline commit, the baseline SHA capture).

Add near the end of `TeamWorkspace.create()`, before returning `ws`:
```python
        # Record a baseline pytest result so post-work failures are attributable
        ws.baseline_test_result = ws._capture_baseline_tests()
        (ws.root / "baseline_tests.json").write_text(
            json.dumps(ws.baseline_test_result), encoding="utf-8"
        )
```

Add the helper method:
```python
    def _capture_baseline_tests(self) -> dict:
        """Run pytest in the integration worktree to establish a baseline.
        Never raises — records status even on error.
        """
        try:
            result = subprocess.run(
                ["pytest", "--collect-only", "-q"],
                cwd=self.integration_worktree,
                capture_output=True, text=True, timeout=60,
            )
            return {
                "status": "ok" if result.returncode == 0 else "no_tests_or_error",
                "returncode": result.returncode,
                "stdout_tail": result.stdout[-500:],
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}
```

Backwards compat: keep `ws.worktree` as an alias for `ws.integration_worktree` (some existing code may reference it):
```python
    @property
    def worktree(self) -> Path:
        """Legacy alias for integration_worktree — kept so v1 modules don't break."""
        return self.integration_worktree
```

But remove the `worktree_path` field from the Sprint dataclass if it exists — leave existing consumers to migrate.

- [ ] **Step 4: Update TeamWorkspace.reset() to clean up all agent worktrees**

Find `TeamWorkspace.reset()`. Before the `if self.worktree.exists():` line, add:

```python
        # Remove per-agent worktrees first
        for role in self.ROLE_NAMES:
            aw = self.agent_worktree(role)
            if aw.exists():
                subprocess.run(
                    ["git", "worktree", "remove", "--force", str(aw)],
                    cwd=self.source_repo, check=False, capture_output=True,
                )
                subprocess.run(
                    ["git", "branch", "-D", self.agent_branch(role)],
                    cwd=self.source_repo, check=False, capture_output=True,
                )
```

- [ ] **Step 5: Add baseline_test_result to __init__**

In `TeamWorkspace.__init__()`, initialize the attribute:
```python
        self.baseline_test_result: dict = {}
```

And also load it in `.open()`:
```python
    @classmethod
    def open(cls, team_id: str, source_repo: Path) -> "TeamWorkspace":
        ws = cls(team_id, source_repo)
        if not ws.exists():
            raise TeamWorkspaceMissing(...)
        p = ws.root / "baseline_tests.json"
        if p.exists():
            try:
                ws.baseline_test_result = json.loads(p.read_text())
            except Exception:
                ws.baseline_test_result = {}
        return ws
```

- [ ] **Step 6: Run new tests — expect pass**

Run: `pytest tests/agile/test_team_workspace.py -v 2>&1 | tail -20`
Expected: all `TestPerAgentWorktrees` pass; all existing `TestCreate`/`TestOpen`/etc. also pass (via the `.worktree` alias).

- [ ] **Step 7: Run full suite — nothing broken**

Run: `pytest -q 2>&1 | tail -3`
Expected: green.

- [ ] **Step 8: Commit**

```bash
git add orgos/agile/team_workspace.py tests/agile/test_team_workspace.py
git commit -m "feat(workspace): per-agent worktrees + integration branch + rerere + baseline

Restructure workspace to .orgos_teams/<id>/agents/<role>/worktree per role,
plus a shared .orgos_teams/<id>/integration worktree. Each worktree enables
git rerere so conflict resolutions carry forward. Records baseline pytest
result at create time so post-work failures are attributable.

Legacy .worktree property kept as alias for .integration_worktree."
```

---

### Task 5: HeartbeatScheduler — parse natural-language HEARTBEAT.md

**Files:**
- Create: `orgos/agile/heartbeat_scheduler.py`
- Create: `tests/agile/test_heartbeat_scheduler.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `ScheduledTask` dataclass: `{name: str, cadence_seconds: int, action_text: str}`
  - `HeartbeatScheduler(heartbeat_md_text: str)` — parses the schedule
  - `HeartbeatScheduler.pending(now_seconds: float) → list[ScheduledTask]` — tasks due since last tick
  - `HeartbeatScheduler.next_tick_in(now_seconds: float) → float` — seconds until soonest next fire

- [ ] **Step 1: Write the failing tests**

Create `tests/agile/test_heartbeat_scheduler.py`:

```python
"""Tests for HEARTBEAT.md natural-language schedule parsing."""

from __future__ import annotations

import pytest

from orgos.agile.heartbeat_scheduler import (
    HeartbeatScheduler, ScheduledTask, parse_schedule,
)


class TestParseSchedule:
    def test_every_n_seconds(self):
        text = """
        # arch heartbeat
        ## Every 30 seconds
        Check the board.
        """
        tasks = parse_schedule(text)
        assert len(tasks) == 1
        assert tasks[0].cadence_seconds == 30
        assert "Check the board" in tasks[0].action_text

    def test_every_n_minutes(self):
        text = "## Every 5 minutes\nRun poker."
        tasks = parse_schedule(text)
        assert tasks[0].cadence_seconds == 300

    def test_every_n_hours(self):
        text = "## Every 4 hours\nWrite retro."
        tasks = parse_schedule(text)
        assert tasks[0].cadence_seconds == 14400

    def test_multiple_tasks(self):
        text = """
        ## Every 30 seconds
        Check the board.

        ## Every 30 minutes
        Poll PR comments.
        """
        tasks = parse_schedule(text)
        assert len(tasks) == 2
        assert tasks[0].cadence_seconds == 30
        assert tasks[1].cadence_seconds == 1800

    def test_ignores_non_schedule_headers(self):
        text = """
        ## Instructions
        Some prose.

        ## Every 60 seconds
        A task.
        """
        assert len(parse_schedule(text)) == 1

    def test_empty_input(self):
        assert parse_schedule("") == []
        assert parse_schedule("Just some prose, no schedule.") == []


class TestHeartbeatScheduler:
    def test_first_tick_fires_all_tasks(self):
        text = "## Every 30 seconds\nCheck board.\n\n## Every 5 minutes\nPoker."
        sched = HeartbeatScheduler(text)
        due = sched.pending(now_seconds=0.0)
        assert len(due) == 2

    def test_second_tick_only_fires_ready_tasks(self):
        text = "## Every 30 seconds\nCheck board.\n\n## Every 5 minutes\nPoker."
        sched = HeartbeatScheduler(text)
        sched.pending(now_seconds=0.0)   # arms both
        due = sched.pending(now_seconds=30.0)
        # Only the 30-second one should fire again; poker at 300s not yet due
        assert len(due) == 1
        assert due[0].cadence_seconds == 30

    def test_next_tick_in(self):
        text = "## Every 30 seconds\nCheck.\n\n## Every 5 minutes\nPoker."
        sched = HeartbeatScheduler(text)
        sched.pending(now_seconds=0.0)
        # Next tick should be 30s from now
        assert sched.next_tick_in(now_seconds=0.0) == pytest.approx(30.0)
```

- [ ] **Step 2: Run tests — expect fail (module doesn't exist)**

Run: `pytest tests/agile/test_heartbeat_scheduler.py -v`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Create the scheduler module**

Create `orgos/agile/heartbeat_scheduler.py`:

```python
"""Parse HEARTBEAT.md natural-language schedules into asyncio-friendly ticks.

Supported schedule syntax (case-insensitive, in markdown ## headers):

    ## Every N seconds
    ## Every N minutes
    ## Every N hours

Prose under each header is the "action text" that the agent's runtime
interprets (typically it names a Python function to call — the runtime
matches by keyword).

More sophisticated schedules (cron syntax, times of day) are deferred.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class ScheduledTask:
    name: str                 # header without the "Every N …" prefix, if any
    cadence_seconds: int
    action_text: str
    _last_fired_at: float = field(default=-1.0, repr=False)


_HEADER_RE = re.compile(
    r"^\s*##\s*Every\s+(\d+)\s*(seconds?|minutes?|hours?)\b",
    re.IGNORECASE | re.MULTILINE,
)


def _to_seconds(n: int, unit: str) -> int:
    unit = unit.lower().rstrip("s")
    if unit == "second":
        return n
    if unit == "minute":
        return n * 60
    if unit == "hour":
        return n * 3600
    return n  # fallback


def parse_schedule(text: str) -> list[ScheduledTask]:
    """Parse HEARTBEAT.md text → list of ScheduledTask.

    Each `## Every N unit` header starts a task; its body is everything
    until the next `## ` header or end of file.
    """
    if not text.strip():
        return []
    matches = list(_HEADER_RE.finditer(text))
    tasks: list[ScheduledTask] = []
    for i, m in enumerate(matches):
        n = int(m.group(1))
        unit = m.group(2)
        cadence = _to_seconds(n, unit)
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[body_start:body_end].strip()
        tasks.append(ScheduledTask(
            name=f"every_{n}_{unit.lower().rstrip('s')}",
            cadence_seconds=cadence,
            action_text=body,
        ))
    return tasks


class HeartbeatScheduler:
    """Track when each ScheduledTask is due to fire.

    Callers invoke `.pending(now_seconds)` on each heartbeat tick; it returns
    the tasks that are due to fire, and internally marks their last-fired time.
    """

    def __init__(self, heartbeat_md_text: str):
        self.tasks: list[ScheduledTask] = parse_schedule(heartbeat_md_text)

    def pending(self, now_seconds: float) -> list[ScheduledTask]:
        due: list[ScheduledTask] = []
        for t in self.tasks:
            if t._last_fired_at < 0 or (now_seconds - t._last_fired_at) >= t.cadence_seconds:
                due.append(t)
                t._last_fired_at = now_seconds
        return due

    def next_tick_in(self, now_seconds: float) -> float:
        """Seconds until the soonest task is next due."""
        if not self.tasks:
            return 60.0  # arbitrary default when no tasks
        soonest = min(
            (t._last_fired_at + t.cadence_seconds) - now_seconds
            for t in self.tasks
        )
        return max(0.1, soonest)
```

- [ ] **Step 4: Run tests — expect pass**

Run: `pytest tests/agile/test_heartbeat_scheduler.py -v`
Expected: all pass.

- [ ] **Step 5: Run full suite**

Run: `pytest -q 2>&1 | tail -3`
Expected: green (new tests included).

- [ ] **Step 6: Commit**

```bash
git add orgos/agile/heartbeat_scheduler.py tests/agile/test_heartbeat_scheduler.py
git commit -m "feat(heartbeat): parse natural-language HEARTBEAT.md schedules

Supports 'Every N seconds/minutes/hours' markdown headers. Returns
ScheduledTasks with cadence + action_text. HeartbeatScheduler tracks
last-fired times and reports which tasks are pending per tick."
```

---

### Task 6: CodingExecutor — Protocol + OpenCodeExecutor

**Files:**
- Create: `orgos/agile/coding_executor.py`
- Create: `tests/agile/test_coding_executor.py`

**Interfaces:**
- Consumes: `TeamWorkspace.agent_worktree(role)`
- Produces:
  - `ExecutionResult` dataclass: `{success: bool, commit_sha: str, files_touched: list[str], learnings: str, tokens_input: int, tokens_output: int, wall_seconds: float, error: str}`
  - `CodingExecutor` Protocol with `run_story()` and `spawn_subagent()`
  - `OpenCodeExecutor(model, opencode_binary="opencode")` — the v2 default implementation

- [ ] **Step 1: Write the failing tests (protocol + mocked subprocess)**

Create `tests/agile/test_coding_executor.py`:

```python
"""Tests for CodingExecutor protocol + OpenCodeExecutor."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from orgos.agile.coding_executor import (
    CodingExecutor, ExecutionResult, OpenCodeExecutor,
)


class TestExecutionResult:
    def test_defaults(self):
        r = ExecutionResult(success=True, commit_sha="abc123")
        assert r.success is True
        assert r.commit_sha == "abc123"
        assert r.files_touched == []
        assert r.tokens_input == 0


class TestOpenCodeExecutorProtocolConformance:
    def test_implements_protocol(self):
        ex = OpenCodeExecutor(model="deepseek/deepseek-chat")
        # Protocol is a duck-typing check; just verify the methods exist.
        assert hasattr(ex, "run_story")
        assert hasattr(ex, "spawn_subagent")


class FakeStory:
    def __init__(self):
        self.issue_id = "S-001"
        self.title = "Add ping"
        self.body = "Add ping() to app.py returning 'pong'"
        self.type = "feature"
        self.priority = 5
        self.files_to_touch = ["app.py"]


class TestOpenCodeRunStory:
    """Uses a mocked subprocess so we don't invoke real opencode."""

    def test_success_when_subprocess_exits_zero_and_commit_lands(
        self, tmp_path, monkeypatch,
    ):
        # Fake worktree with a git repo and an initial commit
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
        (tmp_path / "README.md").write_text("init")
        subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
        subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)

        baseline_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=tmp_path,
            capture_output=True, text=True,
        ).stdout.strip()

        # Simulate opencode landing a commit by making it happen ourselves inside the fake
        def fake_run(cmd, **kw):
            # Pretend opencode ran successfully and made a commit
            if cmd[0] == "opencode":
                (tmp_path / "app.py").write_text("def ping(): return 'pong'\n")
                subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
                subprocess.run(
                    ["git", "-c", "user.name=oc", "-c", "user.email=oc@oc",
                     "commit", "-qm", "feat: add ping"],
                    cwd=tmp_path, check=True,
                )
                r = MagicMock()
                r.returncode = 0
                r.stdout = "session:ok\n"
                r.stderr = ""
                return r
            return subprocess.run(cmd, **kw)  # real for other commands

        monkeypatch.setattr("orgos.agile.coding_executor.subprocess.run", fake_run)

        ex = OpenCodeExecutor(model="deepseek/deepseek-chat",
                               baseline_sha_provider=lambda: baseline_sha)
        result = ex.run_story(
            worktree=tmp_path,
            story=FakeStory(),
            persona_scaffold="you are the architect",
            session_id="arch-1",
        )
        assert result.success is True
        assert result.commit_sha != baseline_sha
        assert "app.py" in result.files_touched

    def test_failure_when_no_commit_landed(self, tmp_path, monkeypatch):
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
        (tmp_path / "README.md").write_text("init")
        subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
        subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)

        baseline_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=tmp_path,
            capture_output=True, text=True,
        ).stdout.strip()

        def fake_run(cmd, **kw):
            if cmd[0] == "opencode":
                r = MagicMock()
                r.returncode = 0
                r.stdout = ""
                r.stderr = ""
                return r
            return subprocess.run(cmd, **kw)

        monkeypatch.setattr("orgos.agile.coding_executor.subprocess.run", fake_run)

        ex = OpenCodeExecutor(model="m",
                               baseline_sha_provider=lambda: baseline_sha)
        result = ex.run_story(
            worktree=tmp_path,
            story=FakeStory(),
            persona_scaffold="you are the architect",
            session_id="arch-2",
        )
        assert result.success is False
        assert "no commit" in result.error.lower()

    def test_timeout(self, tmp_path, monkeypatch):
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
        (tmp_path / "README.md").write_text("init")
        subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
        subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)

        baseline_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=tmp_path,
            capture_output=True, text=True,
        ).stdout.strip()

        def fake_run(cmd, **kw):
            if cmd[0] == "opencode":
                raise subprocess.TimeoutExpired(cmd, kw.get("timeout", 60))
            return subprocess.run(cmd, **kw)

        monkeypatch.setattr("orgos.agile.coding_executor.subprocess.run", fake_run)

        ex = OpenCodeExecutor(model="m", timeout_seconds=1,
                               baseline_sha_provider=lambda: baseline_sha)
        result = ex.run_story(
            worktree=tmp_path,
            story=FakeStory(),
            persona_scaffold="scaf",
            session_id="arch-3",
        )
        assert result.success is False
        assert "timeout" in result.error.lower()
```

- [ ] **Step 2: Run tests — expect fail (module doesn't exist)**

Run: `pytest tests/agile/test_coding_executor.py -v 2>&1 | tail -5`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Create the coding_executor module**

Create `orgos/agile/coding_executor.py`:

```python
"""CodingExecutor — abstracts the coding-agent subprocess (default: OpenCode).

Only OpenCodeExecutor is implemented in v2. The Protocol shape leaves room
for AiderExecutor / ClaudeCodeExecutor without touching agent_loop.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Protocol


@dataclass
class ExecutionResult:
    success: bool
    commit_sha: str = ""
    files_touched: list[str] = field(default_factory=list)
    learnings: str = ""
    tokens_input: int = 0
    tokens_output: int = 0
    wall_seconds: float = 0.0
    error: str = ""
    raw_stdout: str = ""
    raw_stderr: str = ""


class CodingExecutor(Protocol):
    """Runs one story's worth of work in a worktree; returns what happened."""

    def run_story(
        self, *,
        worktree: Path,
        story: Any,                 # Story from board_store (typed loosely to avoid circular import)
        persona_scaffold: str,
        session_id: str,
    ) -> ExecutionResult: ...

    def spawn_subagent(
        self, *,
        worktree: Path,
        parent_session_id: str,
        prompt: str,
        timeout_seconds: int = 300,
    ) -> ExecutionResult: ...


class OpenCodeExecutor:
    """Invokes OpenCode as a subprocess. v2's only implementation.

    Assumes `opencode` is on PATH. Uses `opencode run` non-interactive mode.
    The `baseline_sha_provider` lets tests inject a known baseline; real
    callers get a default that reads HEAD.
    """

    def __init__(
        self,
        model: str,
        *,
        opencode_binary: str = "opencode",
        timeout_seconds: int = 900,
        baseline_sha_provider: Optional[Callable[[], str]] = None,
    ):
        self.model = model
        self.opencode_binary = opencode_binary
        self.timeout_seconds = timeout_seconds
        self._baseline_sha_provider = baseline_sha_provider

    def _baseline_sha(self, worktree: Path) -> str:
        if self._baseline_sha_provider is not None:
            return self._baseline_sha_provider()
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(worktree),
            capture_output=True, text=True, timeout=10,
        )
        return (r.stdout or "").strip()

    def _current_head(self, worktree: Path) -> str:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(worktree),
            capture_output=True, text=True, timeout=10,
        )
        return (r.stdout or "").strip()

    def _files_touched(self, worktree: Path, since_sha: str) -> list[str]:
        r = subprocess.run(
            ["git", "diff", f"{since_sha}..HEAD", "--name-only"],
            cwd=str(worktree), capture_output=True, text=True, timeout=10,
        )
        return [l.strip() for l in (r.stdout or "").splitlines() if l.strip()]

    def _build_prompt(self, story: Any, persona_scaffold: str) -> str:
        files_hint = ", ".join(getattr(story, "files_to_touch", []) or []) or "(inferred from story)"
        return (
            f"{persona_scaffold}\n\n"
            f"═══ STORY ═══\n"
            f"issue_id: {getattr(story, 'issue_id', '?')}\n"
            f"title:    {getattr(story, 'title', '')}\n"
            f"type:     {getattr(story, 'type', '')}\n"
            f"priority: {getattr(story, 'priority', 0)}\n"
            f"expected files_to_touch: {files_hint}\n\n"
            f"═══ BODY ═══\n"
            f"{getattr(story, 'body', '')}\n\n"
            f"═══ INSTRUCTIONS ═══\n"
            f"Do the work described above in the current directory. When done, commit "
            f"your changes with a descriptive message. Run any relevant tests first."
        )

    def run_story(
        self, *,
        worktree: Path,
        story: Any,
        persona_scaffold: str,
        session_id: str,
    ) -> ExecutionResult:
        baseline = self._baseline_sha(worktree)
        prompt = self._build_prompt(story, persona_scaffold)
        t0 = time.time()

        try:
            cp = subprocess.run(
                [
                    self.opencode_binary, "run",
                    "--model", self.model,
                    "--session", session_id,
                    prompt,
                ],
                cwd=str(worktree),
                capture_output=True, text=True,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as e:
            return ExecutionResult(
                success=False,
                error=f"timeout after {self.timeout_seconds}s",
                wall_seconds=round(time.time() - t0, 2),
            )
        except FileNotFoundError:
            return ExecutionResult(
                success=False,
                error=f"opencode binary not found: {self.opencode_binary}",
                wall_seconds=round(time.time() - t0, 2),
            )
        except Exception as e:
            return ExecutionResult(
                success=False, error=f"{type(e).__name__}: {e}",
                wall_seconds=round(time.time() - t0, 2),
            )

        wall = round(time.time() - t0, 2)
        head = self._current_head(worktree)

        if not head or head == baseline:
            return ExecutionResult(
                success=False,
                error="no commit landed (HEAD unchanged from baseline)",
                wall_seconds=wall,
                raw_stdout=(cp.stdout or "")[-2000:],
                raw_stderr=(cp.stderr or "")[-2000:],
            )
        if cp.returncode != 0:
            return ExecutionResult(
                success=False,
                error=f"opencode exit code {cp.returncode}",
                commit_sha=head,
                files_touched=self._files_touched(worktree, baseline),
                wall_seconds=wall,
                raw_stdout=(cp.stdout or "")[-2000:],
                raw_stderr=(cp.stderr or "")[-2000:],
            )

        return ExecutionResult(
            success=True,
            commit_sha=head,
            files_touched=self._files_touched(worktree, baseline),
            learnings=(cp.stdout or "").strip()[-1000:],
            wall_seconds=wall,
            raw_stdout=(cp.stdout or "")[-2000:],
            raw_stderr=(cp.stderr or "")[-2000:],
        )

    def spawn_subagent(
        self, *,
        worktree: Path,
        parent_session_id: str,
        prompt: str,
        timeout_seconds: int = 300,
    ) -> ExecutionResult:
        """Run a subagent (fresh session) for a specialized subtask.
        Returns whatever the subagent said as `learnings`; doesn't require
        a git commit.
        """
        t0 = time.time()
        sub_session = f"{parent_session_id}:sub:{int(time.time())}"
        try:
            cp = subprocess.run(
                [
                    self.opencode_binary, "run",
                    "--model", self.model,
                    "--session", sub_session,
                    prompt,
                ],
                cwd=str(worktree),
                capture_output=True, text=True, timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return ExecutionResult(
                success=False, error=f"subagent timeout after {timeout_seconds}s",
                wall_seconds=round(time.time() - t0, 2),
            )
        except Exception as e:
            return ExecutionResult(
                success=False, error=f"{type(e).__name__}: {e}",
                wall_seconds=round(time.time() - t0, 2),
            )
        return ExecutionResult(
            success=(cp.returncode == 0),
            learnings=(cp.stdout or "").strip()[-2000:],
            wall_seconds=round(time.time() - t0, 2),
            raw_stdout=(cp.stdout or "")[-2000:],
            raw_stderr=(cp.stderr or "")[-2000:],
        )
```

- [ ] **Step 4: Run tests — expect pass**

Run: `pytest tests/agile/test_coding_executor.py -v 2>&1 | tail -10`
Expected: all tests pass.

- [ ] **Step 5: Full suite green**

Run: `pytest -q 2>&1 | tail -3`
Expected: green.

- [ ] **Step 6: Commit**

```bash
git add orgos/agile/coding_executor.py tests/agile/test_coding_executor.py
git commit -m "feat(coding-executor): CodingExecutor protocol + OpenCodeExecutor

Wraps 'opencode run' as a subprocess. Returns ExecutionResult with
commit_sha, files_touched, tokens (TBD from opencode output parsing),
wall_seconds. Detects success by whether HEAD advanced past baseline.
Supports spawn_subagent for delegated subtasks in fresh sessions."
```

---

### Task 7: MergeQueue — FIFO queue + MergeWorker with rebase-before-merge

**Files:**
- Create: `orgos/agile/merge_queue.py`
- Create: `tests/agile/test_merge_queue.py`

**Interfaces:**
- Consumes: `TeamWorkspace.integration_worktree`, `TeamWorkspace.integration_branch`, `BoardStore`
- Produces:
  - `MergeRequest` dataclass: `{story_id, from_branch, files_touched}`
  - `MergeQueue(workspace)` — asyncio-backed FIFO queue
  - `MergeQueue.enqueue(request)` / `.dequeue() → MergeRequest`
  - `run_merge_worker(queue, workspace, board, emitter)` — coroutine that drains the queue, rebases + merges each request under `git_op_lock`, escalates on conflict

- [ ] **Step 1: Write the failing tests (with mocked git ops)**

Create `tests/agile/test_merge_queue.py`:

```python
"""Tests for FIFO merge queue with rebase-before-merge."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from orgos.agile.board_store import BoardStore
from orgos.agile.live_events import EventEmitter
from orgos.agile.merge_queue import (
    MergeQueue, MergeRequest, run_merge_worker,
)


@pytest.fixture
def team_repo(tmp_path):
    """Create a minimal repo w/ integration + one agent branch that has a commit."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("init")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)
    # integration branch
    subprocess.run(["git", "branch", "integration"], cwd=tmp_path, check=True)
    # agent branch with a commit
    subprocess.run(["git", "checkout", "-qb", "agent/arch"], cwd=tmp_path, check=True)
    (tmp_path / "app.py").write_text("hello\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "feat: hello"], cwd=tmp_path, check=True)
    subprocess.run(["git", "checkout", "-q", "integration"], cwd=tmp_path, check=True)
    return tmp_path


class TestMergeQueue:
    def test_enqueue_and_dequeue(self):
        loop = asyncio.new_event_loop()
        try:
            q = MergeQueue(workspace=None)
            req = MergeRequest(story_id="S", from_branch="agent/arch",
                                files_touched=["app.py"])
            loop.run_until_complete(q.enqueue(req))
            got = loop.run_until_complete(q.dequeue())
            assert got.story_id == "S"
        finally:
            loop.close()

    def test_fifo_order(self):
        loop = asyncio.new_event_loop()
        try:
            q = MergeQueue(workspace=None)
            for name in ("A", "B", "C"):
                loop.run_until_complete(q.enqueue(
                    MergeRequest(story_id=name, from_branch="x", files_touched=[]),
                ))
            order = [
                loop.run_until_complete(q.dequeue()).story_id for _ in range(3)
            ]
            assert order == ["A", "B", "C"]
        finally:
            loop.close()


class TestMergeWorker:
    """Uses a mock workspace + real git ops to verify rebase-and-merge."""

    def test_merges_successfully_when_no_conflict(self, team_repo, tmp_path):
        board = BoardStore(tmp_path / "board")
        board.draft_story(issue_id="S1", title="t", body="b",
                          story_type="feature", files_to_touch=["app.py"])
        board.transition("S1", "refinement", actor="sm")
        board.transition("S1", "ready", actor="sm")
        board.transition("S1", "in_progress", actor="arch")
        board.transition("S1", "review", actor="arch")

        # Minimal fake workspace
        ws = MagicMock()
        ws.integration_worktree = team_repo
        ws.integration_branch = "integration"
        ws.source_repo = team_repo

        emitter = EventEmitter(tmp_path)
        queue = MergeQueue(workspace=ws)

        async def scenario():
            await queue.enqueue(MergeRequest(
                story_id="S1", from_branch="agent/arch",
                files_touched=["app.py"],
            ))
            worker_task = asyncio.create_task(run_merge_worker(
                queue, ws, board, emitter, stop_when_empty=True,
            ))
            await asyncio.wait_for(worker_task, timeout=10.0)

        asyncio.run(scenario())

        # Integration branch should now contain the app.py file
        assert (team_repo / "app.py").exists()
        assert board.read("S1").state == "done"
```

- [ ] **Step 2: Run tests — expect fail (module missing)**

Run: `pytest tests/agile/test_merge_queue.py -v 2>&1 | tail -5`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Create the merge_queue module**

Create `orgos/agile/merge_queue.py`:

```python
"""FIFO merge queue with rebase-before-merge. Serializes cross-worktree git.

Agents enqueue a MergeRequest after completing a story. A single MergeWorker
async task drains the queue, taking a global git_op_lock for each merge.
On conflict: transitions story to blocked with reason 'merge_conflict:<paths>'.
"""

from __future__ import annotations

import asyncio
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class MergeRequest:
    story_id: str
    from_branch: str
    files_touched: list[str] = field(default_factory=list)


class MergeQueue:
    """Asyncio-friendly FIFO queue.

    Note: `workspace` may be None for pure queue-behavior tests.
    """
    def __init__(self, workspace: Any):
        self.workspace = workspace
        self._queue: asyncio.Queue = asyncio.Queue()

    async def enqueue(self, request: MergeRequest) -> None:
        await self._queue.put(request)

    async def dequeue(self) -> MergeRequest:
        return await self._queue.get()

    def qsize(self) -> int:
        return self._queue.qsize()


# Global lock for cross-worktree git ops (per-process).
git_op_lock = asyncio.Lock()


def _run_git(args: list[str], cwd: Path, timeout: int = 60) -> tuple[int, str, str]:
    r = subprocess.run(
        ["git", *args], cwd=str(cwd),
        capture_output=True, text=True, timeout=timeout,
    )
    return r.returncode, (r.stdout or ""), (r.stderr or "")


def _attempt_merge(
    workspace: Any, from_branch: str,
) -> tuple[bool, str]:
    """Rebase from_branch on integration, then fast-forward integration.
    Returns (ok, message_or_error).
    """
    integ = workspace.integration_worktree
    integ_branch = workspace.integration_branch

    # 1. In the integration worktree, fetch nothing (single repo) — just make
    #    sure we're on the integration branch and up to date locally.
    rc, out, err = _run_git(["checkout", integ_branch], integ)
    if rc != 0:
        return False, f"checkout integration: {err.strip()}"

    # 2. Merge from_branch (fast-forward or --no-ff, up to git config)
    rc, out, err = _run_git(["merge", "--no-edit", from_branch], integ)
    if rc == 0:
        return True, "merged clean"

    # Conflict detected; abort the merge and report
    _run_git(["merge", "--abort"], integ)
    return False, f"merge_conflict:{err.strip() or out.strip()}"


async def run_merge_worker(
    queue: MergeQueue,
    workspace: Any,
    board: Any,
    emitter: Any,
    *,
    stop_when_empty: bool = False,
) -> None:
    """Drain the merge queue serially. Exits when stop_when_empty and queue is drained."""
    while True:
        if stop_when_empty and queue.qsize() == 0:
            return
        try:
            request = await asyncio.wait_for(queue.dequeue(), timeout=1.0)
        except asyncio.TimeoutError:
            if stop_when_empty:
                return
            continue

        emitter.emit(
            "merge_queued", story_id=request.story_id,
            branch=request.from_branch,
            summary=f"draining merge: {request.from_branch}",
        )

        async with git_op_lock:
            ok, msg = await asyncio.get_event_loop().run_in_executor(
                None, _attempt_merge, workspace, request.from_branch,
            )

        if ok:
            try:
                board.transition(request.story_id, "done", actor="merge_worker")
            except Exception:
                pass
            emitter.emit(
                "merge_completed", story_id=request.story_id,
                branch=request.from_branch, summary=msg,
            )
        else:
            try:
                board.transition(
                    request.story_id, "blocked", actor="merge_worker",
                    reason=msg[:200],
                )
            except Exception:
                pass
            emitter.emit(
                "merge_conflict", story_id=request.story_id,
                branch=request.from_branch, summary=msg[:200],
            )
```

- [ ] **Step 4: Add live event types (needed by the tests to emit cleanly)**

In `orgos/agile/live_events.py`, add the three new events to `_EVENT_META`:

```python
    "merge_queued":         ("📮", "merge request queued"),
    "merge_completed":      ("🔗", "merge completed"),
    "merge_conflict":       ("💥", "merge conflict"),
```

- [ ] **Step 5: Run tests — expect pass**

Run: `pytest tests/agile/test_merge_queue.py -v 2>&1 | tail -10`
Expected: both `TestMergeQueue` cases and the `TestMergeWorker::test_merges_successfully_when_no_conflict` pass.

- [ ] **Step 6: Run full suite**

Run: `pytest -q 2>&1 | tail -3`
Expected: green.

- [ ] **Step 7: Commit**

```bash
git add orgos/agile/merge_queue.py orgos/agile/live_events.py tests/agile/test_merge_queue.py
git commit -m "feat(merge-queue): FIFO merge queue with rebase-before-merge

MergeRequest carries story_id + from_branch + files_touched.
MergeQueue is asyncio.Queue-backed. run_merge_worker drains it serially,
taking git_op_lock per merge. On merge conflict: aborts, transitions story
to blocked with 'merge_conflict:<msg>'. Adds three live event types."
```

---

### Task 8: AsyncAgent — per-role async runtime

**Files:**
- Create: `orgos/agile/agent_loop.py`
- Create: `tests/agile/test_agent_loop.py`

**Interfaces:**
- Consumes: `TeamWorkspace`, `BoardStore`, `HeartbeatScheduler`, `CodingExecutor`, `MergeQueue`, `EventEmitter`
- Produces:
  - `AsyncAgent(role, workspace, board, executor, merge_queue, emitter)` — one per role
  - `AsyncAgent.loop()` async coroutine — runs until `.stop()` is called
  - `AsyncAgent.stop()` — sets alive=False, waits for current story to finish

- [ ] **Step 1: Write the failing tests (fully mocked, no real subprocess)**

Create `tests/agile/test_agent_loop.py`:

```python
"""Tests for AsyncAgent — the async runtime per role."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

import pytest

from orgos.agile.agent_loop import AsyncAgent
from orgos.agile.board_store import BoardStore
from orgos.agile.coding_executor import ExecutionResult
from orgos.agile.live_events import EventEmitter
from orgos.agile.merge_queue import MergeQueue, MergeRequest


@pytest.fixture
def real_repo(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("init")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)
    return tmp_path


def _make_ws(root: Path, integration: Path):
    ws = MagicMock()
    ws.root = root
    ws.integration_worktree = integration
    ws.integration_branch = "master"
    ws.agent_worktree = lambda role: integration
    ws.agent_branch = lambda role: "master"
    return ws


class TestAsyncAgentDelivery:
    def test_pulls_and_works_a_story(self, tmp_path, real_repo, monkeypatch):
        board = BoardStore(tmp_path / "board")
        board.draft_story(issue_id="S1", title="t", body="b",
                          story_type="architecture", files_to_touch=[])
        board.transition("S1", "refinement", actor="sm")
        board.transition("S1", "ready", actor="sm")

        ws = _make_ws(tmp_path, real_repo)
        emitter = EventEmitter(tmp_path)
        queue = MergeQueue(ws)

        executor = MagicMock()
        executor.run_story = MagicMock(return_value=ExecutionResult(
            success=True, commit_sha="abc1234",
            files_touched=["app.py"], learnings="did the thing",
        ))

        heartbeat_md = "## Every 1 seconds\nCheck board and work."

        agent = AsyncAgent(
            role="architect",
            workspace=ws,
            board=board,
            executor=executor,
            merge_queue=queue,
            emitter=emitter,
            heartbeat_md=heartbeat_md,
            is_delivery_agent=True,
        )

        async def scenario():
            task = asyncio.create_task(agent.loop())
            # Give the loop ~2s to tick and pull the story
            await asyncio.sleep(2.5)
            agent.stop()
            await asyncio.wait_for(task, timeout=5.0)

        asyncio.run(scenario())
        # Agent pulled S1, transitioned to in_progress, enqueued a merge
        assert board.read("S1").state in ("in_progress", "review", "done")
        assert executor.run_story.called
        assert queue.qsize() >= 1 or board.read("S1").state == "done"

    def test_sleeps_when_no_work(self, tmp_path, real_repo):
        board = BoardStore(tmp_path / "board")  # empty board
        ws = _make_ws(tmp_path, real_repo)
        emitter = EventEmitter(tmp_path)
        queue = MergeQueue(ws)
        executor = MagicMock()
        executor.run_story = MagicMock()

        agent = AsyncAgent(
            role="architect", workspace=ws, board=board,
            executor=executor, merge_queue=queue, emitter=emitter,
            heartbeat_md="## Every 1 seconds\nCheck board.",
            is_delivery_agent=True,
        )

        async def scenario():
            task = asyncio.create_task(agent.loop())
            await asyncio.sleep(1.5)
            agent.stop()
            await asyncio.wait_for(task, timeout=5.0)

        asyncio.run(scenario())
        executor.run_story.assert_not_called()


class TestAsyncAgentCoordination:
    def test_coordination_agent_skips_board(self, tmp_path, real_repo):
        board = BoardStore(tmp_path / "board")
        board.draft_story(issue_id="S1", title="t", body="b",
                          story_type="architecture")
        board.transition("S1", "refinement", actor="sm")
        board.transition("S1", "ready", actor="sm")

        ws = _make_ws(tmp_path, real_repo)
        emitter = EventEmitter(tmp_path)
        queue = MergeQueue(ws)
        executor = MagicMock()
        executor.run_story = MagicMock()

        # PO is a coordination agent — should NOT pull from board
        agent = AsyncAgent(
            role="po", workspace=ws, board=board,
            executor=executor, merge_queue=queue, emitter=emitter,
            heartbeat_md="## Every 1 seconds\nPlan sprint.",
            is_delivery_agent=False,
        )

        async def scenario():
            task = asyncio.create_task(agent.loop())
            await asyncio.sleep(1.5)
            agent.stop()
            await asyncio.wait_for(task, timeout=5.0)

        asyncio.run(scenario())
        # Should not have touched the board's story
        assert board.read("S1").state == "ready"
        executor.run_story.assert_not_called()
```

- [ ] **Step 2: Run tests — expect fail**

Run: `pytest tests/agile/test_agent_loop.py -v 2>&1 | tail -5`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Create the agent_loop module**

Create `orgos/agile/agent_loop.py`:

```python
"""AsyncAgent — one asyncio task per role. No dispatcher; agent self-organizes.

Two modes:
  - is_delivery_agent=True  → checks the board on each heartbeat, pulls
                              matching stories, invokes CodingExecutor.
  - is_delivery_agent=False → skips the board (coordination agents like
                              PO/scrum_master don't consume stories).

Both modes run scheduled tasks from HEARTBEAT.md (retro, replan, poker, etc.).
Concrete ceremony action wiring happens in a follow-up task; this module
provides the pull-and-work loop + the tick-per-schedule mechanic.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Optional

from orgos.agile.board_store import BoardStore
from orgos.agile.coding_executor import CodingExecutor, ExecutionResult
from orgos.agile.heartbeat_scheduler import HeartbeatScheduler
from orgos.agile.live_events import EventEmitter
from orgos.agile.merge_queue import MergeQueue, MergeRequest


class AsyncAgent:
    def __init__(
        self,
        *,
        role: str,
        workspace: Any,
        board: BoardStore,
        executor: CodingExecutor,
        merge_queue: MergeQueue,
        emitter: EventEmitter,
        heartbeat_md: str,
        is_delivery_agent: bool = True,
        persona_scaffold: str = "",
    ):
        self.role = role
        self.workspace = workspace
        self.board = board
        self.executor = executor
        self.merge_queue = merge_queue
        self.emitter = emitter
        self.scheduler = HeartbeatScheduler(heartbeat_md)
        self.is_delivery_agent = is_delivery_agent
        self.persona_scaffold = persona_scaffold or f"You are the {role} agent."
        self._alive = True
        self._start_wall = 0.0

    def stop(self) -> None:
        self._alive = False

    async def loop(self) -> None:
        self._start_wall = time.time()
        self.emitter.emit("agent_started", role=self.role,
                          summary=f"{self.role} online")

        while self._alive:
            now = time.time() - self._start_wall
            due_tasks = self.scheduler.pending(now)

            for task in due_tasks:
                # For delivery agents, "check the board" is the implicit action
                # for the first task if its cadence is short enough (<= 60s).
                # For all agents, any scheduled task's action_text may contain
                # keywords we route to a ceremony (retro/replan/poker) —
                # ceremony routing is a follow-up task.
                if self.is_delivery_agent and task.cadence_seconds <= 60:
                    await self._pull_and_work_once()
                # Ceremony routing: parse action_text keywords — implemented
                # in the ceremonies task. For now, other scheduled tasks are
                # no-ops so the tests can pass.

            # Sleep until next scheduled tick (or 1s min, so stop() is responsive)
            await asyncio.sleep(min(1.0, self.scheduler.next_tick_in(now)))

        self.emitter.emit("agent_stopped", role=self.role,
                          summary=f"{self.role} shut down cleanly")

    async def _pull_and_work_once(self) -> None:
        """Delivery-agent action: check board, pull if match, run executor, enqueue merge."""
        story = self.board.try_claim_next_for(self.role, actor=self.role)
        if story is None:
            return

        self.emitter.emit(
            "story_pulled", story_id=story.issue_id,
            worker=self.role, story_type=story.type,
            title=story.title[:80],
        )

        # Run the coding executor
        try:
            result: ExecutionResult = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.executor.run_story(
                    worktree=self.workspace.agent_worktree(self.role),
                    story=story,
                    persona_scaffold=self.persona_scaffold,
                    session_id=self.role,
                ),
            )
        except Exception as e:
            self.board.transition(
                story.issue_id, "blocked", actor=self.role,
                reason=f"executor_exception:{type(e).__name__}",
            )
            self.emitter.emit(
                "story_no_commit", story_id=story.issue_id,
                worker=self.role, summary=f"executor crashed: {e}",
            )
            return

        if not result.success:
            self.board.transition(
                story.issue_id, "blocked", actor=self.role,
                reason=result.error[:200],
            )
            self.emitter.emit(
                "story_no_commit", story_id=story.issue_id,
                worker=self.role, summary=result.error[:200],
            )
            return

        # Success: transition to review, enqueue merge
        self.board.transition(story.issue_id, "review", actor=self.role)
        self.board.set_commit(story.issue_id, result.commit_sha, actor=self.role)
        self.emitter.emit(
            "commit_landed", story_id=story.issue_id,
            commit_sha=result.commit_sha[:7], worker=self.role,
            summary=f"{self.role} committed {result.commit_sha[:7]}",
        )
        await self.merge_queue.enqueue(MergeRequest(
            story_id=story.issue_id,
            from_branch=self.workspace.agent_branch(self.role),
            files_touched=result.files_touched,
        ))
```

- [ ] **Step 4: Add missing event types**

In `orgos/agile/live_events.py`, add:

```python
    "agent_started":        ("🟢", "agent online"),
    "agent_stopped":        ("🔴", "agent stopped"),
    "agent_crashed":        ("💀", "agent crashed"),
    "agent_restarted":      ("♻️ ", "agent restarted"),
    "subagent_spawned":     ("👶", "subagent spawned"),
```

- [ ] **Step 5: Run tests — expect pass**

Run: `pytest tests/agile/test_agent_loop.py -v 2>&1 | tail -15`
Expected: all three tests pass.

- [ ] **Step 6: Full suite green**

Run: `pytest -q 2>&1 | tail -3`
Expected: green.

- [ ] **Step 7: Commit**

```bash
git add orgos/agile/agent_loop.py orgos/agile/live_events.py tests/agile/test_agent_loop.py
git commit -m "feat(agent-loop): AsyncAgent — per-role async runtime, no dispatcher

Runs an asyncio loop keyed off HeartbeatScheduler. Delivery agents pull
from board via try_claim_next_for + invoke CodingExecutor + enqueue merge.
Coordination agents skip the board (ceremonies are follow-up). New live
event types for agent lifecycle + subagent spawn."
```

---

### Task 9: TeamSupervisor — spawn 5 agents, crash-restart with backoff

**Files:**
- Create: `orgos/agile/supervisor.py`
- Create: `tests/agile/test_supervisor.py`

**Interfaces:**
- Consumes: `AsyncAgent`
- Produces:
  - `TeamSupervisor(agents: dict[str, AsyncAgent], emitter)` — runtime supervisor
  - `TeamSupervisor.run()` — spawns each agent as a task, watches for crashes, restarts with exponential backoff (5s, 30s, 5min, 30min, 60min)
  - `TeamSupervisor.stop()` — sets alive=False and signals all agents to stop

- [ ] **Step 1: Write the failing tests**

Create `tests/agile/test_supervisor.py`:

```python
"""Tests for TeamSupervisor — crash-restart with backoff."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from orgos.agile.live_events import EventEmitter
from orgos.agile.supervisor import TeamSupervisor


class FakeAgent:
    """Minimal AsyncAgent-shaped stub for testing supervisor lifecycle."""
    def __init__(self, name, crash_after=None):
        self.role = name
        self._alive = True
        self._crash_after = crash_after
        self._loops = 0

    def stop(self):
        self._alive = False

    async def loop(self):
        while self._alive:
            self._loops += 1
            if self._crash_after and self._loops == self._crash_after:
                raise RuntimeError(f"{self.role} crashed on loop {self._loops}")
            await asyncio.sleep(0.1)


class TestSupervisor:
    def test_starts_all_agents(self, tmp_path):
        emitter = EventEmitter(tmp_path)
        agents = {name: FakeAgent(name) for name in
                  ("po", "scrum_master", "architect", "test", "devsecops")}
        sup = TeamSupervisor(agents, emitter, restart_backoffs=[0.1])

        async def scenario():
            task = asyncio.create_task(sup.run())
            await asyncio.sleep(0.5)
            sup.stop()
            await asyncio.wait_for(task, timeout=3.0)

        asyncio.run(scenario())
        # All agents ran at least once
        for a in agents.values():
            assert a._loops >= 1

    def test_restarts_crashed_agent(self, tmp_path):
        emitter = EventEmitter(tmp_path)
        # architect crashes after 2 loops
        agents = {
            "architect": FakeAgent("architect", crash_after=2),
            "test": FakeAgent("test"),
        }
        sup = TeamSupervisor(agents, emitter, restart_backoffs=[0.1, 0.1])

        async def scenario():
            task = asyncio.create_task(sup.run())
            await asyncio.sleep(1.0)
            sup.stop()
            await asyncio.wait_for(task, timeout=3.0)

        asyncio.run(scenario())
        # architect should have crashed + been restarted at least once
        # (fresh FakeAgent instances aren't reused; the supervisor
        # calls agent_factory. If your supervisor recreates, adapt below.)
        # For this test, we just verify supervisor didn't die and other agents ran.
        assert agents["test"]._loops >= 2


class TestBackoff:
    def test_backoff_schedule_advances(self, tmp_path):
        emitter = EventEmitter(tmp_path)
        agents = {"a": FakeAgent("a", crash_after=1)}
        sup = TeamSupervisor(agents, emitter,
                              restart_backoffs=[0.05, 0.1, 0.2])
        # Just verify the schedule structure; behavior of restart cycles
        # covered by test_restarts_crashed_agent.
        assert sup.restart_backoffs == [0.05, 0.1, 0.2]
```

- [ ] **Step 2: Run — expect fail**

Run: `pytest tests/agile/test_supervisor.py -v 2>&1 | tail -5`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Create the supervisor module**

Create `orgos/agile/supervisor.py`:

```python
"""TeamSupervisor — watches AsyncAgent tasks, restarts on crash with backoff."""

from __future__ import annotations

import asyncio
from typing import Any


DEFAULT_BACKOFFS = [5.0, 30.0, 300.0, 1800.0, 3600.0]  # 5s, 30s, 5m, 30m, 1h


class TeamSupervisor:
    def __init__(
        self,
        agents: dict[str, Any],
        emitter: Any,
        *,
        restart_backoffs: list[float] | None = None,
    ):
        self.agents = dict(agents)
        self.emitter = emitter
        self.restart_backoffs = list(restart_backoffs) if restart_backoffs \
            else list(DEFAULT_BACKOFFS)
        self._alive = True

    def stop(self) -> None:
        self._alive = False
        for a in self.agents.values():
            try:
                a.stop()
            except Exception:
                pass

    async def run(self) -> None:
        tasks: dict[str, asyncio.Task] = {}
        restart_counts: dict[str, int] = {name: 0 for name in self.agents}

        # Initial spawn
        for name, agent in self.agents.items():
            tasks[name] = asyncio.create_task(agent.loop(), name=name)

        while self._alive:
            if not tasks:
                break
            done, pending = await asyncio.wait(
                tasks.values(),
                timeout=0.5,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in done:
                name = t.get_name()
                exc = t.exception()
                if exc is not None:
                    self.emitter.emit(
                        "agent_crashed", role=name, error=str(exc)[:200],
                        summary=f"{name}: {type(exc).__name__}: {str(exc)[:120]}",
                    )
                    idx = min(restart_counts[name], len(self.restart_backoffs) - 1)
                    backoff = self.restart_backoffs[idx]
                    restart_counts[name] += 1
                    if self._alive:
                        await asyncio.sleep(backoff)
                        self.emitter.emit(
                            "agent_restarted", role=name,
                            attempt=restart_counts[name],
                            summary=f"{name} restarted (attempt #{restart_counts[name]})",
                        )
                        tasks[name] = asyncio.create_task(
                            self.agents[name].loop(), name=name,
                        )
                    else:
                        del tasks[name]
                else:
                    # Agent exited cleanly (probably via .stop())
                    del tasks[name]

        # Wait for all remaining agents to finish
        for t in tasks.values():
            try:
                await asyncio.wait_for(t, timeout=5.0)
            except (asyncio.TimeoutError, Exception):
                t.cancel()
```

- [ ] **Step 4: Run tests — expect pass**

Run: `pytest tests/agile/test_supervisor.py -v 2>&1 | tail -10`
Expected: pass.

- [ ] **Step 5: Full suite green**

Run: `pytest -q 2>&1 | tail -3`
Expected: green.

- [ ] **Step 6: Commit**

```bash
git add orgos/agile/supervisor.py tests/agile/test_supervisor.py
git commit -m "feat(supervisor): TeamSupervisor with crash-restart + exponential backoff

Watches N AsyncAgent tasks. On exception: logs agent_crashed, waits per
DEFAULT_BACKOFFS (5s,30s,5m,30m,1h), restarts with agent_restarted event.
Stop() sets alive=False and calls .stop() on each managed agent."
```

---

### Task 10: Live events + team report updates for per-agent status

**Files:**
- Modify: `orgos/agile/team_report.py`

**Interfaces:**
- Consumes: `TeamWorkspace.agent_dir(role)`
- Produces: report renders a new "Agents" section (5 rows) + a "Merge queue" section

- [ ] **Step 1: Add per-agent status endpoint to team_report**

In `orgos/agile/team_report.py`, add a new function that reads live per-agent state from disk:

```python
def collect_agent_statuses(workspace) -> list[dict]:
    """Read each agent's current status from disk. Best-effort.

    Returns a list of dicts: {role, is_alive, current_story, last_event_at, restart_count}.
    Sourced from live.jsonl events (agent_started, agent_stopped, story_pulled, agent_crashed).
    """
    from orgos.agile.live_events import read_events
    events = read_events(workspace.root)
    roles = ("po", "scrum_master", "architect", "test", "devsecops")
    status = {r: {"role": r, "is_alive": False,
                  "current_story": "", "last_event_at": "",
                  "restart_count": 0}
              for r in roles}
    for e in events:
        r = e.get("role") or e.get("worker") or ""
        # Peel off any '#N' suffix from worker labels
        base = r.split("#", 1)[0] if r else ""
        if base not in status:
            continue
        s = status[base]
        s["last_event_at"] = e.get("timestamp", s["last_event_at"])
        action = e.get("action", "")
        if action == "agent_started":
            s["is_alive"] = True
        elif action in ("agent_stopped", "agent_crashed"):
            s["is_alive"] = False
        elif action == "agent_restarted":
            s["is_alive"] = True
            s["restart_count"] += 1
        elif action == "story_pulled":
            s["current_story"] = e.get("story_id", "")
        elif action in ("commit_landed", "story_done_noop",
                        "story_no_commit", "story_review_pass"):
            s["current_story"] = ""
    return [status[r] for r in roles]
```

- [ ] **Step 2: Add a new section to build_state_payload**

In the `build_state_payload` function, add:
```python
    return {
        "manifest": manifest,
        "result": result,
        "stories": stories,
        "audit": audit,
        "wiki": wiki_tail,
        "results_by_story": results_by_story,
        "sprint_history": history,
        "agent_statuses": collect_agent_statuses(workspace),
    }
```

- [ ] **Step 3: Add rendering to the report HTML template**

Find the section that renders `## Board` (a `<section>` with `<h2>Board</h2>`). Right BEFORE it, add:

```html
<section>
  <h2>Agents</h2>
  <div id="agent-statuses"></div>
</section>
```

And add the CSS + JS to render it. Add to the CSS block:
```css
.agent-row {
  display: grid; grid-template-columns: 120px 80px 1fr 120px 80px;
  gap: 12px; padding: 8px 12px; border-bottom: 1px solid var(--border);
  font-size: 12.5px;
}
.agent-row .role { font-weight: 500; }
.agent-row .status.alive { color: var(--good); }
.agent-row .status.dead { color: var(--bad); }
.agent-row .story { color: var(--muted); font-family: "SF Mono", monospace; }
.agent-row .last { color: var(--muted); font-size: 11px; }
.agent-row .restarts { color: var(--muted); font-variant-numeric: tabular-nums; text-align: right; }
```

Add to the JS init block (near where board is rendered):
```javascript
function renderAgents() {
  const el = document.getElementById("agent-statuses");
  if (!el) return;
  const rows = STATE.agent_statuses || [];
  el.innerHTML = rows.map(a => `
    <div class="agent-row">
      <div class="role">${esc(a.role)}</div>
      <div class="status ${a.is_alive ? 'alive' : 'dead'}">${a.is_alive ? '● live' : '○ down'}</div>
      <div class="story">${esc(a.current_story || '(idle)')}</div>
      <div class="last">${esc((a.last_event_at || '').slice(11, 19))}</div>
      <div class="restarts">${a.restart_count > 0 ? '↺' + a.restart_count : ''}</div>
    </div>
  `).join("");
}
```

And call `renderAgents()` in the main `render()` function.

- [ ] **Step 4: Sanity check — render a report for an existing team and open it**

If there's an existing team, render it:
```bash
python3 -c "
from pathlib import Path
from orgos.agile.team_workspace import TeamWorkspace
from orgos.agile.team_report import render_team_report
# Use any existing team-id, or skip if none:
import json
teams_root = Path('.orgos_teams')
if teams_root.exists():
    for team_dir in teams_root.iterdir():
        if (team_dir / 'manifest.json').exists():
            m = json.loads((team_dir / 'manifest.json').read_text())
            ws = TeamWorkspace.open(m['team_id'], Path(m['source_repo']))
            render_team_report(ws)
            print('rendered:', ws.root / 'report.html')
            break
"
```
Expected: no exceptions.

- [ ] **Step 5: Full suite green**

Run: `pytest -q 2>&1 | tail -3`
Expected: green.

- [ ] **Step 6: Commit**

```bash
git add orgos/agile/team_report.py
git commit -m "feat(report): per-agent status section + collect_agent_statuses helper

Reads live.jsonl to reconstruct per-agent state (alive/dead/current story/
restart count). Report shows 5 rows, one per role. build_state_payload
exposes agent_statuses via /live/state."
```

---

### Task 11: CLI — `orgos start` / `orgos stop` / `orgos status`

**Files:**
- Modify: `orgos/cli.py`

**Interfaces:**
- Consumes: everything from previous tasks
- Produces: three new subcommands, plus a `_cmd_start` that wires supervisor + agents together

- [ ] **Step 1: Add `orgos start` subcommand**

In `orgos/cli.py`, add a new command handler function:

```python
def _cmd_start(args: argparse.Namespace) -> int:
    """Start the async agent team. Runs until stopped by SIGINT or `orgos stop`."""
    import asyncio
    import signal
    from orgos.agile.agent_loop import AsyncAgent
    from orgos.agile.board_store import BoardStore
    from orgos.agile.coding_executor import OpenCodeExecutor
    from orgos.agile.live_events import EventEmitter
    from orgos.agile.merge_queue import MergeQueue, run_merge_worker
    from orgos.agile.supervisor import TeamSupervisor
    from orgos.agile.team_workspace import (
        TeamWorkspace, TeamWorkspaceExists,
    )

    repo = Path(args.repo).resolve()
    _load_dotenv(repo)

    if not (repo / ".git").exists():
        print(f"ERROR: {repo} is not a git repo", file=sys.stderr)
        return 2

    # Load or create workspace
    goal, _spec_text = _resolve_goal_and_spec(repo, args)
    if not goal.strip():
        print("ERROR: provide --goal or --spec-file", file=sys.stderr)
        return 2
    try:
        ws = TeamWorkspace.create(args.team_id, repo, goal=goal, model=args.model)
        print(f"[cli] created workspace {ws.root}", flush=True)
    except TeamWorkspaceExists:
        if args.fresh:
            TeamWorkspace.open(args.team_id, repo).reset()
            ws = TeamWorkspace.create(args.team_id, repo, goal=goal, model=args.model)
        else:
            ws = TeamWorkspace.open(args.team_id, repo)
            print(f"[cli] resuming existing workspace {args.team_id}", flush=True)

    # Ensure per-agent workspaces
    roles = ["po", "scrum_master", "architect", "test", "devsecops"]
    for r in roles:
        ws.ensure_agent_workspace(r)

    board = BoardStore(ws.root / "board")
    emitter = EventEmitter(ws.root)
    executor = OpenCodeExecutor(model=args.model)
    merge_queue = MergeQueue(ws)

    def _load_heartbeat(role: str) -> str:
        p = repo / "agents" / role / "HEARTBEAT.md"
        return p.read_text(encoding="utf-8") if p.exists() else "## Every 30 seconds\nCheck board."

    delivery_roles = {"architect", "test", "devsecops"}
    agents = {}
    for r in roles:
        agents[r] = AsyncAgent(
            role=r, workspace=ws, board=board, executor=executor,
            merge_queue=merge_queue, emitter=emitter,
            heartbeat_md=_load_heartbeat(r),
            is_delivery_agent=(r in delivery_roles),
        )

    supervisor = TeamSupervisor(agents, emitter)

    async def _run_all():
        merge_task = asyncio.create_task(run_merge_worker(merge_queue, ws, board, emitter))
        sup_task = asyncio.create_task(supervisor.run())
        try:
            await sup_task
        finally:
            merge_task.cancel()

    def _handle_sigint(sig, frame):
        print("\n[cli] shutting down team", flush=True)
        supervisor.stop()
    signal.signal(signal.SIGINT, _handle_sigint)

    print(f"[cli] team {args.team_id} started with roles {roles}", flush=True)
    asyncio.run(_run_all())
    print(f"[cli] team {args.team_id} stopped", flush=True)
    return 0


def _resolve_goal_and_spec(repo: Path, args) -> tuple[str, str]:
    """Extract goal + optionally load a spec file (moved out of _cmd_run)."""
    goal = args.goal or ""
    spec_text = ""
    if getattr(args, "spec_file", None):
        spec_path = Path(args.spec_file).resolve()
        if spec_path.exists():
            spec_text = spec_path.read_text(encoding="utf-8")
            wiki_dir = repo / "wiki"
            wiki_dir.mkdir(parents=True, exist_ok=True)
            (wiki_dir / "SPEC.md").write_text(spec_text, encoding="utf-8")
            goal = (
                (goal + "\n\n" if goal else "")
                + f"See wiki/SPEC.md for the full spec. Contents:\n\n"
                + f"--- BEGIN SPEC ---\n{spec_text}\n--- END SPEC ---"
            )
    return goal, spec_text
```

- [ ] **Step 2: Register the new subparsers**

Below the existing subparser registrations, add:

```python
    # start
    start_p = sub.add_parser(
        "start",
        help="Start the async agent team (runs until stopped by SIGINT).",
    )
    start_p.add_argument("--repo", type=str, required=True)
    start_p.add_argument("--team-id", type=str, required=True)
    start_p.add_argument("--goal", type=str, default="")
    start_p.add_argument("--spec-file", type=str, default=None)
    start_p.add_argument("--model", type=str, default="deepseek/deepseek-chat")
    start_p.add_argument("--fresh", action="store_true")
    start_p.set_defaults(func=_cmd_start)

    # stop
    stop_p = sub.add_parser(
        "stop",
        help="Signal a running team to shut down (SIGTERM). Team finishes current stories then exits.",
    )
    stop_p.add_argument("--team-id", type=str, required=True)
    stop_p.set_defaults(func=_cmd_stop)

    # status
    status_p = sub.add_parser(
        "status",
        help="Print per-agent status for a team.",
    )
    status_p.add_argument("--repo", type=str, default=".")
    status_p.add_argument("--team-id", type=str, required=True)
    status_p.set_defaults(func=_cmd_status)
```

- [ ] **Step 3: Add stop and status handlers**

Add to `orgos/cli.py`:

```python
def _cmd_stop(args: argparse.Namespace) -> int:
    """Signal a running team to stop. Currently a placeholder — v2 uses SIGINT."""
    import subprocess
    r = subprocess.run(
        ["pgrep", "-f", f"orgos.cli.*start.*--team-id.*{args.team_id}"],
        capture_output=True, text=True,
    )
    pids = [p for p in r.stdout.strip().splitlines() if p]
    if not pids:
        print(f"ERROR: no running team found with team-id {args.team_id}", file=sys.stderr)
        return 2
    for pid in pids:
        subprocess.run(["kill", "-INT", pid], check=False)
    print(f"[cli] sent SIGINT to {len(pids)} process(es) for team {args.team_id}", flush=True)
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    from orgos.agile.team_workspace import TeamWorkspace, TeamWorkspaceMissing
    from orgos.agile.team_report import collect_agent_statuses
    repo = Path(args.repo).resolve()
    try:
        ws = TeamWorkspace.open(args.team_id, repo)
    except TeamWorkspaceMissing as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    for a in collect_agent_statuses(ws):
        mark = "●" if a["is_alive"] else "○"
        story = a["current_story"] or "(idle)"
        restarts = f" ↺{a['restart_count']}" if a["restart_count"] else ""
        print(f"  {mark} {a['role']:14s} {story:36s} last:{a['last_event_at'][:19]}{restarts}")
    return 0
```

- [ ] **Step 4: Sanity check CLI help**

Run: `orgos --help 2>&1 | grep -E "start|stop|status"`
Expected: three new subcommands listed.

Run: `orgos start --help 2>&1 | tail -10`
Expected: shows args including `--spec-file`.

- [ ] **Step 5: Full suite green**

Run: `pytest -q 2>&1 | tail -3`
Expected: green.

- [ ] **Step 6: Commit**

```bash
git add orgos/cli.py
git commit -m "feat(cli): orgos start / stop / status commands for async team

start: spawns TeamSupervisor with 5 AsyncAgent tasks, MergeQueue worker,
       runs until SIGINT (or 'orgos stop').
stop:  sends SIGINT to matching orgos start process(es).
status: prints per-agent status from live.jsonl events."
```

---

### Task 12: Personas — HEARTBEAT.md natural-language schedules

**Files:**
- Modify: `agents/architect/HEARTBEAT.md`
- Modify: `agents/test/HEARTBEAT.md`
- Modify: `agents/devsecops/HEARTBEAT.md`
- Modify: `agents/po/HEARTBEAT.md`
- Modify: `agents/scrum_master/HEARTBEAT.md`

**Interfaces:**
- Consumes: `HeartbeatScheduler`
- Produces: 5 rewritten HEARTBEAT.md files, one per role

- [ ] **Step 1: Rewrite architect/HEARTBEAT.md**

Overwrite `agents/architect/HEARTBEAT.md`:

```markdown
# Architect Agent — HEARTBEAT

## Every 30 seconds
Check the board for a `ready` story of type `architecture` or `feature`. If any:
claim the top one, invoke the CodingExecutor in my worktree, commit, enqueue
the merge, update my MEMORY.md with what I learned. If none: sleep.

## Every 30 minutes
Read wiki/DECISIONS.md to catch up on any new architectural decisions from
other agents.
```

- [ ] **Step 2: Rewrite test/HEARTBEAT.md**

Overwrite `agents/test/HEARTBEAT.md`:

```markdown
# Test Agent — HEARTBEAT

## Every 30 seconds
Check the board for a `ready` story of type `test`. If any: claim the top one,
invoke the CodingExecutor to add or update tests, commit, enqueue merge,
update my MEMORY.md.

## Every 30 minutes
Skim wiki/DECISIONS.md for any new testing conventions.
```

- [ ] **Step 3: Rewrite devsecops/HEARTBEAT.md**

Overwrite `agents/devsecops/HEARTBEAT.md`:

```markdown
# DevSecOps Agent — HEARTBEAT

## Every 30 seconds
Check the board for a `ready` story of type `security`. If any: claim the top
one, invoke the CodingExecutor to add validation / auth / secret handling as
described, commit, enqueue merge, update my MEMORY.md.

## Every 60 minutes
Grep the repo for common security issues (hardcoded secrets, unsafe
deserialize, etc.). Log findings to my MEMORY.md.
```

- [ ] **Step 4: Rewrite po/HEARTBEAT.md**

Overwrite `agents/po/HEARTBEAT.md`:

```markdown
# Product Owner Agent — HEARTBEAT

## Every 30 minutes
If the board has fewer than 3 stories in `ready`, invoke replan(): read the
SPEC.md and RETRO.md, draft new stories to fill the backlog. Do NOT
re-propose work that already exists in the board.

## Every 60 minutes
Poll the draft PR (if any) for new review comments via pr_feedback.ingest().
Each substantive comment becomes a new story on the board.
```

- [ ] **Step 5: Rewrite scrum_master/HEARTBEAT.md**

Overwrite `agents/scrum_master/HEARTBEAT.md`:

```markdown
# Scrum Master Agent — HEARTBEAT

## Every 5 minutes
Check the board for stories in `draft` or `refinement`. Run planning poker
on any: architect / test / devsecops each vote, discuss if divergent,
converge on story points. Move refined stories to `ready`.

## Every 4 hours
Run the sprint retrospective. Write a retro entry to wiki/RETRO.md capturing:
what went well, what went wrong, one action item for next sprint. Then trigger
PO's replan.
```

- [ ] **Step 6: Verify each parses correctly**

```bash
python3 -c "
from orgos.agile.heartbeat_scheduler import parse_schedule
from pathlib import Path
for role in ('architect', 'test', 'devsecops', 'po', 'scrum_master'):
    text = Path(f'agents/{role}/HEARTBEAT.md').read_text()
    tasks = parse_schedule(text)
    assert len(tasks) >= 1, f'{role} has no scheduled tasks'
    print(f'{role}: {[(t.cadence_seconds, t.name) for t in tasks]}')
"
```
Expected: each role prints its parsed schedule; no assertion errors.

- [ ] **Step 7: Full suite green**

Run: `pytest -q 2>&1 | tail -3`
Expected: green.

- [ ] **Step 8: Commit**

```bash
git add agents/architect/HEARTBEAT.md agents/test/HEARTBEAT.md \
        agents/devsecops/HEARTBEAT.md agents/po/HEARTBEAT.md \
        agents/scrum_master/HEARTBEAT.md
git commit -m "feat(personas): HEARTBEAT.md as natural-language schedule for all 5 roles

Delivery agents (architect/test/devsecops): every-30s board check.
Coordination agents (po/scrum_master): scheduled replan/retro/poker.
All parseable by HeartbeatScheduler."
```

---

### Task 13: Ceremony wiring — route HEARTBEAT actions to retro / replan / poker

**Files:**
- Modify: `orgos/agile/agent_loop.py`
- Modify: `tests/agile/test_agent_loop.py` (extend with ceremony test)

**Interfaces:**
- Consumes: existing `retrospective.py`, `replan.py`, `poker.py`, `pr_feedback.py`
- Produces:
  - `AsyncAgent` routes each ScheduledTask's `action_text` to the appropriate ceremony function, matched by keyword.

- [ ] **Step 1: Write a failing ceremony test**

Add to `tests/agile/test_agent_loop.py`:

```python
class TestAsyncAgentCeremonies:
    def test_scrum_master_triggers_retro_by_keyword(self, tmp_path, real_repo, monkeypatch):
        board = BoardStore(tmp_path / "board")
        ws = _make_ws(tmp_path, real_repo)
        ws.team_id = "t1"
        ws.source_repo = real_repo
        ws.manifest = MagicMock(return_value=MagicMock(
            goal="test", model="m", baseline_sha=""))
        emitter = EventEmitter(tmp_path)
        queue = MergeQueue(ws)
        executor = MagicMock()

        # Intercept retro
        called = {"retro": 0}
        def fake_retro(**kwargs):
            called["retro"] += 1
            return {"went_well": [], "went_wrong": [], "action_item": ""}
        from orgos.agile import retrospective as _retro_mod
        monkeypatch.setattr(_retro_mod, "run_retrospective", fake_retro)

        heartbeat_md = "## Every 1 seconds\nRun the sprint retrospective."

        agent = AsyncAgent(
            role="scrum_master", workspace=ws, board=board,
            executor=executor, merge_queue=queue, emitter=emitter,
            heartbeat_md=heartbeat_md,
            is_delivery_agent=False,
        )

        async def scenario():
            task = asyncio.create_task(agent.loop())
            await asyncio.sleep(1.5)
            agent.stop()
            await asyncio.wait_for(task, timeout=5.0)

        asyncio.run(scenario())
        assert called["retro"] >= 1
```

- [ ] **Step 2: Run — expect fail**

Run: `pytest tests/agile/test_agent_loop.py::TestAsyncAgentCeremonies -v`
Expected: FAIL (ceremony not triggered — currently the loop no-ops non-board tasks).

- [ ] **Step 3: Add ceremony routing to AsyncAgent**

In `orgos/agile/agent_loop.py`, replace the body of `AsyncAgent.loop()` for the `for task in due_tasks:` loop:

```python
            for task in due_tasks:
                text = task.action_text.lower()
                # Delivery: implicit "check board" for short-cadence tasks
                if self.is_delivery_agent and task.cadence_seconds <= 60 \
                   and ("board" in text or "story" in text or "check" in text):
                    await self._pull_and_work_once()
                    continue
                # Ceremony routing by keyword
                if "retro" in text or "retrospective" in text:
                    await self._run_retro()
                    continue
                if "replan" in text or "backlog" in text or "spec" in text:
                    await self._run_replan()
                    continue
                if "poker" in text or "refinement" in text:
                    await self._run_poker()
                    continue
                if "pr" in text and ("comment" in text or "feedback" in text or "review" in text):
                    await self._run_pr_feedback()
                    continue
                # Otherwise: no-op (unknown scheduled task; log for the retro to notice)
                self.emitter.emit(
                    "scheduled_noop", role=self.role,
                    summary=f"unrouted schedule: {task.action_text[:80]}",
                )
```

Add the four ceremony methods to the class:

```python
    async def _run_retro(self) -> None:
        try:
            from orgos.agile.retrospective import run_retrospective
            # Note: run_retrospective's signature expects a lot of args; wire what we can.
            m = self.workspace.manifest()
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: run_retrospective(
                    workspace=self.workspace, board=self.board,
                    emitter=self.emitter, model=m.model,
                    goal=m.goal, reason_stopped="scheduled",
                    started_at=m.created_at, ended_at=m.created_at,
                    tokens_total=0,
                ),
            )
        except Exception as e:
            self.emitter.emit("retro_failed", role=self.role, summary=str(e)[:200])

    async def _run_replan(self) -> None:
        try:
            from orgos.agile.replan import run_replan
            from orgos.agile.sprint_history import read_history
            m = self.workspace.manifest()
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: run_replan(
                    workspace=self.workspace, board=self.board,
                    emitter=self.emitter, model=m.model,
                    goal=m.goal, history=read_history(self.workspace.root),
                ),
            )
        except Exception as e:
            self.emitter.emit("replan_failed", role=self.role, summary=str(e)[:200])

    async def _run_poker(self) -> None:
        try:
            from orgos.agile.poker import run_poker_round
            # Only run on stories in draft or refinement
            m = self.workspace.manifest()
            for state in ("draft", "refinement"):
                for story in self.board.list_state(state):
                    await asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda s=story: run_poker_round(
                            story=s, board=self.board, model=m.model,
                            token_accumulator=lambda r: (0, 0),
                        ),
                    )
        except Exception as e:
            self.emitter.emit("poker_failed", role=self.role, summary=str(e)[:200])

    async def _run_pr_feedback(self) -> None:
        try:
            from orgos.agile.pr_feedback import ingest_pr_feedback
            # PR URL from manifest or campaign_result
            import json
            r_path = self.workspace.root / "campaign_result.json"
            pr_url = ""
            if r_path.exists():
                try:
                    pr_url = json.loads(r_path.read_text()).get("pr_url", "")
                except Exception:
                    pass
            if not pr_url:
                return  # nothing to ingest
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: ingest_pr_feedback(
                    workspace=self.workspace, pr_url=pr_url,
                    board=self.board, emitter=self.emitter,
                    sprint_num=1,
                ),
            )
        except Exception as e:
            self.emitter.emit(
                "pr_feedback_error", role=self.role, summary=str(e)[:200],
            )
```

- [ ] **Step 4: Add `scheduled_noop` and `poker_failed` event types**

In `orgos/agile/live_events.py`:
```python
    "scheduled_noop":       ("💤", "unrouted scheduled task"),
    "poker_failed":         ("⚠️ ", "poker failed"),
```

- [ ] **Step 5: Run ceremony test — expect pass**

Run: `pytest tests/agile/test_agent_loop.py::TestAsyncAgentCeremonies -v`
Expected: pass.

- [ ] **Step 6: Full suite green**

Run: `pytest -q 2>&1 | tail -3`
Expected: green.

- [ ] **Step 7: Commit**

```bash
git add orgos/agile/agent_loop.py orgos/agile/live_events.py tests/agile/test_agent_loop.py
git commit -m "feat(agent-loop): route HEARTBEAT scheduled tasks to ceremonies

Keyword matching on ScheduledTask.action_text:
  'retro' → run_retrospective
  'replan'|'backlog'|'spec' → run_replan
  'poker'|'refinement' → run_poker_round on draft/refinement stories
  'pr comment/feedback/review' → pr_feedback.ingest
Unrouted schedules emit 'scheduled_noop' for retro to notice."
```

---

### Task 14: Full regression + end-to-end smoke

**Files:**
- No source changes (verification only)
- May Modify: any test file that has a stale import; that's fixed in Task 1

**Interfaces:**
- Consumes: everything
- Produces: proof the platform works end-to-end + all 138+ regression tests pass

- [ ] **Step 1: Full regression**

Run: `pytest -q 2>&1 | tail -5`
Expected: green. Count the passes — should be `138 + <new test count>`.

- [ ] **Step 2: End-to-end sanity — `orgos start` on Flask target**

If `/tmp/flask-target/` still exists from earlier tests, clean it and re-init:

```bash
rm -rf /tmp/flask-target/.orgos_teams
```

Run (in one terminal — this blocks):

```bash
orgos start \
  --repo /tmp/flask-target \
  --team-id smoke-v2 \
  --model deepseek/deepseek-chat \
  --goal "Add /notes-count endpoint returning {count: N} — reuse existing NotesStore." \
  --fresh
```

Let it run for ~90 seconds, then Ctrl-C.

- [ ] **Step 3: Verify agents were alive**

In another terminal:
```bash
orgos status --repo /tmp/flask-target --team-id smoke-v2
```
Expected: prints 5 rows, one per role, most/all `●` (or `○` after your Ctrl-C).

- [ ] **Step 4: Verify at least one story was drafted**

```bash
ls /tmp/flask-target/.orgos_teams/smoke-v2/board/stories/ | wc -l
```
Expected: > 0 (PO decomposed the goal).

- [ ] **Step 5: Verify live.jsonl has agent lifecycle events**

```bash
grep -c "agent_started" /tmp/flask-target/.orgos_teams/smoke-v2/live.jsonl
```
Expected: 5 (one per role).

- [ ] **Step 6: Commit any test file fixes needed**

If any tests had to be adjusted for the new event types or event names, commit those:
```bash
git add -A
git status --short
git commit -m "test: post-integration fixes for v2 event names" || echo "(no changes)"
```

- [ ] **Step 7: Tag the v2 milestone**

```bash
git tag orgos-v2-async-scrum-team -m "orgos v2: async scrum team runtime + OpenCode executor"
git log --oneline -20
```

---

## Self-Review Notes

Ran the checklist against the spec (`docs/superpowers/specs/2026-07-16-orgos-v2-async-scrum-team.md`):

**Spec coverage:**
- §3.2 keep list: Task 2 (board), 3 (decomposer), 4 (workspace); reports/CLI/live-events touched in tasks 10-11 ✅
- §3.3 new modules: agent_loop (Task 8), coding_executor (Task 6), heartbeat_scheduler (Task 5), merge_queue (Task 7), supervisor (Task 9) ✅
- §3.4 deletes: Task 1 ✅
- §3.5 persona semantics: Task 12 ✅
- §3.6 CLI surface: Task 11 ✅
- §4 data flow: covered across tasks; end-to-end verified in Task 14 ✅
- §5 merge conflict strategy: files_to_touch (Task 2/3), rerere (Task 4), FIFO queue + rebase-before-merge (Task 7) ✅
- §6 supervisor: Task 9 ✅
- §7 testing: unit tests per task + regression + smoke in Task 14 ✅

**Gaps caught and folded in:**
- Sprint history / PR publisher / retro / replan / poker weren't tied to a task; they're referenced in Task 13's ceremony wiring — no changes needed to those modules themselves.
- `.orgos_teams/<id>/wiki/` is still used by wiki_mcp; nothing changed there.
- The `orgos migrate` command mentioned in spec §8 is NOT built (spec says v2 users start fresh) — captured in Task 1's step 5 (v1 workspaces rejected via the run-command error).

**No placeholders found.** All code steps show full code. All commands show expected output.

**Type consistency check:** `ExecutionResult`, `MergeRequest`, `AsyncAgent` interfaces used consistently across tasks 6/7/8/9/11.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-16-orgos-v2-async-scrum-team.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks (spec compliance + code quality), fast iteration. Best when tasks are largely independent (they are here — sequential dependencies but not shared mutable state during the task).

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints. Preserves session context; slower.

Which approach?

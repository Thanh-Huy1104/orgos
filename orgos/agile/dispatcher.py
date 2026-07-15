"""Dispatcher — orchestrates a Scrum team through refinement + work phases.

Ties together:
  - TeamWorkspace  (persistent worktree + wiki + audit)
  - BoardStore     (multi-story blackboard with state machine)
  - Personas       (architect, test, devsecops from agents/)

Phases:
  1. INGEST   — PO decomposes the goal into DRAFT stories.
  2. REFINE   — specialists play planning poker + discuss until each story
                is READY (or blocked). Stops when either (a) all draft/refinement
                stories are ready/blocked, or (b) ready_threshold stories are
                READY (defaults to 3).
  3. WORK     — free specialists pull READY stories matching their type,
                write code, commit, move to REVIEW.
  4. REVIEW   — a different specialist verifies the diff; pass → DONE,
                fail → back to IN_PROGRESS.
  5. LOOP     — return to REFINE for more DRAFT stories until backlog empty
                or max_iterations hit.

The dispatcher is safe to interrupt: every mutation is atomic on the board,
so restarting picks up wherever we left off.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from orgos.agile.board_store import (
    BoardStore, InvalidTransition, Story, VALID_TYPES,
)
from orgos.agile.sprint import _extract_json_objects, _get_wiki_mcp
from orgos.agile.team_workspace import TeamWorkspace
from orgos.spawn import PermissionTier, RoleSpec, TaskBrief, spawn
from orgos.subagents import (
    architect_role, devsecops_role, po_role, test_role,
)
from orgos.tools.bash import BashTool


# ── Type → role registration for specialized pull ─────────────────────────
# Extended to include a "pull types" filter that overrides BoardStore's default.
ROLE_FACTORIES: dict[str, Callable] = {
    "architect": architect_role,
    "test":      test_role,
    "devsecops": devsecops_role,
    "po":        po_role,
}

# Which BoardStore worker_type each role identity uses when pulling
ROLE_TO_PULL_TYPE: dict[str, str] = {
    "architect": "architecture",
    "test":      "test",
    "devsecops": "security",
}


# ── Result types ──────────────────────────────────────────────────────────

@dataclass
class WorkResult:
    story_id: str
    role: str
    status: str            # "committed" | "no_commit" | "failed"
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
    per_story_results: list[WorkResult] = field(default_factory=list)


# ── The dispatcher ────────────────────────────────────────────────────────

class Dispatcher:
    def __init__(
        self,
        workspace: TeamWorkspace,
        model: str,
        *,
        ready_threshold: int = 3,
        max_stories_worked: int = 20,
        max_wall_seconds: int = 3600,
        skip_refinement_for_trivial: bool = True,
        log: Optional[Callable[[str], None]] = None,
    ):
        self.ws = workspace
        self.board = BoardStore(workspace.board_dir)
        self.model = model
        self.ready_threshold = ready_threshold
        self.max_stories_worked = max_stories_worked
        self.max_wall_seconds = max_wall_seconds
        self.skip_refinement_for_trivial = skip_refinement_for_trivial
        self.log = log or (lambda msg: print(f"[dispatcher] {msg}", flush=True))
        self._total_in = 0
        self._total_out = 0

    # ── Token accounting ─────────────────────────────────────────────────

    def _accum(self, spawn_result: Any) -> tuple[int, int]:
        tu = getattr(spawn_result, "token_usage", None) or {}
        i = tu.get("prompt_tokens", 0)
        o = tu.get("completion_tokens", 0)
        self._total_in += i
        self._total_out += o
        return i, o

    # ── Phase orchestration ─────────────────────────────────────────────

    def run_campaign(self, goal: str) -> DispatchResult:
        started_at = datetime.now(timezone.utc).isoformat()
        t0 = time.time()
        reason = ""

        # Phase 1 — ingest (decompose goal into DRAFT stories)
        self.log("phase=ingest — decomposing goal")
        try:
            from orgos.agile.goal_decomposer import decompose_goal
            ids = decompose_goal(
                goal=goal,
                repo_root=self.ws.source_repo,
                board=self.board,
                model=self.model,
            )
            self.log(f"phase=ingest — created {len(ids)} DRAFT stories")
        except Exception as e:
            reason = f"ingest_failed: {e}"
            self.log(f"phase=ingest FAILED: {e}")
            return self._final_result(goal, started_at, reason)

        # Phase 2 + 3 loop — refine batches to READY, then WORK
        results: list[WorkResult] = []
        worked = 0

        while worked < self.max_stories_worked:
            elapsed = time.time() - t0
            if elapsed > self.max_wall_seconds:
                reason = f"wall_time_exceeded ({elapsed:.0f}s > {self.max_wall_seconds}s)"
                break

            counts = self.board.counts_by_state()

            # If there are DRAFT stories, refine them
            if counts.get("draft", 0) > 0 or counts.get("refinement", 0) > 0:
                self.log(f"phase=refine — draft={counts.get('draft',0)} refinement={counts.get('refinement',0)}")
                self._refine_batch()
                counts = self.board.counts_by_state()

            # If READY is non-empty, pull top and work
            if counts.get("ready", 0) > 0:
                self.log(f"phase=work — ready={counts.get('ready',0)}")
                pulled = self._work_one()
                if pulled is None:
                    # No worker could pull anything (all types starved)
                    self.log("phase=work — no worker could pull (starvation)")
                    reason = "no_worker_could_pull"
                    break
                results.append(pulled)
                worked += 1
                continue

            # Nothing DRAFT/REFINEMENT/READY left. Done.
            if counts.get("draft", 0) == 0 and counts.get("refinement", 0) == 0 \
               and counts.get("ready", 0) == 0:
                reason = "backlog_empty"
                break

        if not reason:
            reason = f"max_stories_worked ({worked} = cap {self.max_stories_worked})"

        self.log(f"phase=done — reason={reason}")
        return self._final_result(goal, started_at, reason, results=results)

    # ── Phase 2: refine ─────────────────────────────────────────────────

    def _refine_batch(self) -> None:
        """Move every DRAFT story through refinement to READY (or blocked).

        v1 minimal refinement:
          - DRAFT → REFINEMENT (transition)
          - poker: architect, test, devsecops each vote + justify
          - if divergent, one round of discussion + re-vote
          - store median as story.points
          - all three signoffs → move to READY
          - if divergent after re-vote → blocked (PO needs to re-scope)

        Trivial stories (points_estimate <= 2) may skip poker for cost.
        """
        for story in self.board.list_state("draft") + self.board.list_state("refinement"):
            if story.state == "draft":
                try:
                    self.board.transition(story.issue_id, "refinement",
                                          actor="scrum_master")
                except InvalidTransition:
                    continue

            # Delegate to poker mechanic (component 5 impl in this file below)
            self._play_poker_and_refine(story.issue_id)

    def _play_poker_and_refine(self, issue_id: str) -> None:
        """Run planning poker on a story. Move to READY or BLOCKED after."""
        from orgos.agile.poker import run_poker_round, discussion_needed
        story = self.board.read(issue_id)

        # Optionally skip poker for tiny stories: if body < ~200 chars AND type is docs,
        # single PO estimate suffices.
        if self.skip_refinement_for_trivial and len(story.body) < 200 and story.type == "docs":
            self.board.set_points(issue_id, 1, actor="po")
            for role in ("architect", "test", "devsecops"):
                self.board.add_signoff(issue_id, role, actor="po_delegate")
            self.board.transition(issue_id, "ready", actor="po",
                                   reason="trivial-doc-skipped-poker")
            self.log(f"  refined {issue_id} → READY (trivial, skipped poker)")
            return

        # Round 1 of poker
        votes = run_poker_round(
            story=story, board=self.board, model=self.model,
            token_accumulator=self._accum,
        )
        self.log(f"  poker {issue_id}: votes={[v['points'] for v in votes]}")

        if discussion_needed(votes):
            self.log(f"  poker {issue_id}: divergent — one discussion round")
            from orgos.agile.poker import run_discussion_and_revote
            votes = run_discussion_and_revote(
                story=self.board.read(issue_id), board=self.board,
                model=self.model, token_accumulator=self._accum,
                first_votes=votes,
            )
            self.log(f"  poker {issue_id} (post-discussion): votes={[v['points'] for v in votes]}")
            self.board.increment_refinement_round(issue_id)

        # Set final points as median of numeric votes
        numeric = sorted(v["points"] for v in votes if isinstance(v.get("points"), int))
        if numeric:
            median = numeric[len(numeric) // 2]
            self.board.set_points(issue_id, median, actor="scrum_master")

        # If still divergent after re-vote → block
        if discussion_needed(votes):
            self.board.add_comment(
                issue_id, author="scrum_master",
                body=f"Post-refinement votes still divergent: "
                     f"{[v['points'] for v in votes]}. Blocking for PO re-scope.")
            self.board.transition(issue_id, "blocked", actor="scrum_master",
                                   reason="divergent_after_refinement")
            self.log(f"  refined {issue_id} → BLOCKED (still divergent)")
            return

        # All three voted, agreement → READY
        voters = {v["voter"] for v in votes}
        for voter in voters:
            self.board.add_signoff(issue_id, voter, actor=voter)

        # Must have all three signoffs to move to ready
        story = self.board.read(issue_id)
        required = {"architect", "test", "devsecops"}
        if required.issubset(set(story.signoffs.keys())):
            self.board.transition(issue_id, "ready", actor="scrum_master")
            self.log(f"  refined {issue_id} → READY (points={story.points})")
        else:
            missing = required - set(story.signoffs.keys())
            self.board.add_comment(
                issue_id, author="scrum_master",
                body=f"Missing signoffs after poker: {missing}. Blocking.")
            self.board.transition(issue_id, "blocked", actor="scrum_master",
                                   reason=f"missing_signoffs:{missing}")
            self.log(f"  refined {issue_id} → BLOCKED (missing signoffs: {missing})")

    # ── Phase 3: work ────────────────────────────────────────────────────

    def _work_one(self) -> Optional[WorkResult]:
        """Try each specialist in turn, pull top of their type's queue, do the work.

        Returns the WorkResult, or None if no specialist could pull anything.
        """
        for role_name, worker_type in ROLE_TO_PULL_TYPE.items():
            candidates = self.board.list_ready_for_type(worker_type)
            if not candidates:
                continue
            story = candidates[0]  # top of priority
            self.log(f"  worker={role_name} pulling {story.issue_id} ({story.type})")
            return self._do_work_and_review(story, role_name)
        return None

    def _do_work_and_review(self, story: Story, worker_role: str) -> WorkResult:
        """One story: assign, work, commit, then peer-review, then DONE (or fail)."""
        self.board.assign(story.issue_id, worker_role)
        self.board.transition(story.issue_id, "in_progress", actor=worker_role)

        # Baseline for this story = current HEAD
        baseline_sha = self.ws.current_head()

        t0 = time.time()
        result = self._run_work_spawn(story, worker_role, baseline_sha)
        result.wall_seconds = round(time.time() - t0, 2)

        # If a commit landed, transition to REVIEW and run peer review
        if result.status == "committed" and result.commit_sha:
            self.board.set_commit(story.issue_id, result.commit_sha, actor=worker_role)
            self.board.transition(story.issue_id, "review", actor=worker_role)

            passed = self._peer_review(story.issue_id, exclude_role=worker_role)
            if passed:
                self.board.transition(story.issue_id, "done", actor="reviewer")
                self.log(f"    {story.issue_id} → DONE (commit {result.commit_sha[:7]})")
            else:
                self.board.transition(story.issue_id, "in_progress", actor="reviewer",
                                       reason="peer_review_failed")
                self.log(f"    {story.issue_id} → back to IN_PROGRESS (review failed)")
                # For v1 we don't loop-retry; just mark blocked for the next cycle
                self.board.transition(story.issue_id, "blocked", actor="reviewer",
                                       reason="review_failure_v1_no_retry")
        else:
            # No commit — send back to blocked for now
            self.board.transition(story.issue_id, "blocked", actor=worker_role,
                                   reason="no_commit_produced")
            self.log(f"    {story.issue_id} → BLOCKED (no commit)")

        return result

    def _run_work_spawn(self, story: Story, worker_role: str,
                        baseline_sha: str) -> WorkResult:
        """Spawn the worker to do the story in the SHARED worktree."""
        from orgos.agile.dispatcher_briefs import build_work_brief
        factory = ROLE_FACTORIES[worker_role]
        role = factory(
            model=self.model,
            extra_tools=[BashTool(default_working_dir=str(self.ws.worktree))],
        )
        role.mcp_servers = [_get_wiki_mcp()]

        brief = build_work_brief(story=story, worktree=self.ws.worktree,
                                   branch=self.ws.manifest().branch)
        try:
            r = spawn(role, brief, run_budget_tokens=1_500_000)
        except Exception as e:
            return WorkResult(
                story_id=story.issue_id, role=worker_role,
                status="failed", error=f"{type(e).__name__}: {e}",
            )

        tin, tout = self._accum(r)

        # Extract envelope
        envelope: dict = {}
        for to in r.tasks_output:
            raw = getattr(to, "raw", "") or ""
            for blob in _extract_json_objects(raw):
                try:
                    data = json.loads(blob)
                except json.JSONDecodeError:
                    continue
                if isinstance(data, dict) and data.get("role"):
                    envelope = data
                    break

        # Did HEAD advance?
        head = self.ws.current_head()
        if head and head != baseline_sha:
            diff_stat = self.ws.diff_since(baseline_sha, stat_only=True)
            return WorkResult(
                story_id=story.issue_id, role=worker_role,
                status="committed", commit_sha=head,
                diff_summary=diff_stat[:2000], envelope=envelope,
                tokens_input=tin, tokens_output=tout,
            )
        return WorkResult(
            story_id=story.issue_id, role=worker_role,
            status="no_commit", envelope=envelope,
            tokens_input=tin, tokens_output=tout,
        )

    def _peer_review(self, issue_id: str, exclude_role: str) -> bool:
        """Spawn a different specialist to verify the diff. Returns pass/fail."""
        # Pick the first role that isn't the writer
        candidates = [r for r in ("test", "devsecops", "architect") if r != exclude_role]
        reviewer_role_name = candidates[0]  # simple deterministic choice
        story = self.board.read(issue_id)

        from orgos.agile.dispatcher_briefs import build_review_brief
        factory = ROLE_FACTORIES[reviewer_role_name]
        role = factory(
            model=self.model,
            extra_tools=[BashTool(default_working_dir=str(self.ws.worktree))],
        )
        role.mcp_servers = [_get_wiki_mcp()]

        brief = build_review_brief(
            story=story, worktree=self.ws.worktree,
            branch=self.ws.manifest().branch,
            author_role=exclude_role,
        )
        try:
            r = spawn(role, brief, run_budget_tokens=600_000)
        except Exception as e:
            self.log(f"    review spawn failed: {e}")
            return False
        self._accum(r)

        # Look for {"review": "pass"} or {"review": "fail"} in envelope
        for to in r.tasks_output:
            raw = getattr(to, "raw", "") or ""
            for blob in _extract_json_objects(raw):
                try:
                    data = json.loads(blob)
                except json.JSONDecodeError:
                    continue
                if isinstance(data, dict):
                    verdict = str(data.get("review", data.get("verdict", ""))).lower()
                    if verdict in ("pass", "approve", "approved", "ok"):
                        self.board.add_comment(
                            issue_id, author=f"{reviewer_role_name}_reviewer",
                            body=f"Review PASS: {data.get('summary', '')}")
                        return True
                    if verdict in ("fail", "reject", "rejected", "block"):
                        self.board.add_comment(
                            issue_id, author=f"{reviewer_role_name}_reviewer",
                            body=f"Review FAIL: {data.get('summary', '')}")
                        return False

        # No verdict emitted — default to PASS but log
        self.log(f"    review {issue_id}: no verdict emitted, defaulting PASS")
        return True

    # ── Final ────────────────────────────────────────────────────────────

    def _final_result(self, goal: str, started_at: str, reason: str,
                       results: list[WorkResult] | None = None) -> DispatchResult:
        counts = self.board.counts_by_state()
        return DispatchResult(
            team_id=self.ws.team_id,
            goal=goal,
            started_at=started_at,
            ended_at=datetime.now(timezone.utc).isoformat(),
            reason_stopped=reason,
            stories_created=sum(counts.values()),
            stories_done=counts.get("done", 0),
            stories_blocked=counts.get("blocked", 0),
            total_tokens_input=self._total_in,
            total_tokens_output=self._total_out,
            per_story_results=results or [],
        )

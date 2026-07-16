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
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from orgos.agile.board_store import (
    BoardStore, InvalidTransition, Story, VALID_TYPES,
)
from orgos.agile.environment import detect_environment
from orgos.agile.live_events import EventEmitter
from orgos.agile.sprint import _extract_json_objects, _get_wiki_mcp
from orgos.agile.team_workspace import TeamWorkspace
from orgos.spawn import PermissionTier, RoleSpec, TaskBrief, spawn
from orgos.subagents import (
    architect_role, devsecops_role, po_role, test_role,
)
from orgos.tools.bash import BashTool
from orgos.tools.fs_tools import EditFileTool, ReadFileTool, WriteFileTool


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
    pr_url: str = ""


# ── The dispatcher ────────────────────────────────────────────────────────

class Dispatcher:
    def __init__(
        self,
        workspace: TeamWorkspace,
        model: str,
        *,
        role_models: Optional[dict[str, str]] = None,
        n_workers: int = 1,
        ready_threshold: int = 3,
        max_stories_worked: int = 20,
        max_wall_seconds: int = 3600,
        skip_refinement_for_trivial: bool = True,
        open_pr: bool = False,
        pr_base: str = "main",
        log: Optional[Callable[[str], None]] = None,
    ):
        self.ws = workspace
        self.board = BoardStore(workspace.board_dir)
        self.model = model  # default model for any role without an override
        self.role_models = role_models or {}
        self.n_workers = max(1, int(n_workers))
        self.ready_threshold = ready_threshold
        self.max_stories_worked = max_stories_worked
        self.max_wall_seconds = max_wall_seconds
        self.skip_refinement_for_trivial = skip_refinement_for_trivial
        self.open_pr = open_pr
        self.pr_base = pr_base
        self.log = log or (lambda msg: print(f"[dispatcher] {msg}", flush=True))
        self.emitter = EventEmitter(workspace.root, console_log=self.log)
        self._total_in = 0
        self._total_out = 0
        self._accum_lock = threading.Lock()   # concurrent workers touch token counters
        self._board_lock = threading.Lock()   # concurrent workers race to pull stories
        self.env = detect_environment(workspace.source_repo)  # for worker briefs

    def _model_for(self, role: str) -> str:
        """Resolve the model to use for a given role (falls back to self.model)."""
        return self.role_models.get(role, self.model)

    # ── Token accounting ─────────────────────────────────────────────────

    def _accum(self, spawn_result: Any) -> tuple[int, int]:
        tu = getattr(spawn_result, "token_usage", None) or {}
        i = tu.get("prompt_tokens", 0)
        o = tu.get("completion_tokens", 0)
        with self._accum_lock:
            self._total_in += i
            self._total_out += o
        return i, o

    # ── Phase orchestration ─────────────────────────────────────────────

    def run_campaign(self, goal: str) -> DispatchResult:
        """Run one Scrum sprint against `goal`.

        Sprint is timeboxed by (max_stories_worked, max_wall_seconds). It ends
        naturally when the ready backlog empties OR either bound is hit. At
        sprint end, a mandatory retrospective ceremony writes to wiki/RETRO.md.
        If --open-pr, a draft PR is pushed after the retro.

        Named run_campaign for backwards compat with tests; the concept is
        ONE sprint.
        """
        started_at = datetime.now(timezone.utc).isoformat()
        t0 = time.time()
        reason = ""

        self.emitter.emit("campaign_started", mode="scrum", goal=goal[:200])

        # Phase 1 — ingest (decompose goal into DRAFT stories)
        self.emitter.emit("goal_ingest_start", summary="PO decomposing goal")
        try:
            from orgos.agile.goal_decomposer import (
                decompose_goal, detect_decomposition_overlaps,
            )
            ids = decompose_goal(
                goal=goal,
                repo_root=self.ws.source_repo,
                board=self.board,
                model=self._model_for("po"),
            )
            self.emitter.emit("goal_ingest_done", n_stories=len(ids),
                              summary=f"created {len(ids)} DRAFT stories")
            for iid in ids:
                s = self.board.read(iid)
                self.emitter.emit("story_drafted", story_id=iid,
                                  title=s.title, type=s.type, priority=s.priority)
            # Sanity pass — flag likely overlaps for human visibility
            try:
                warnings = detect_decomposition_overlaps(self.board, ids)
                for w in warnings:
                    self.emitter.emit(
                        "decomposition_warning",
                        story_id=w["story_a"],
                        other=w["story_b"],
                        shared_paths=w["shared_paths"],
                        summary=(f"may overlap with {w['story_b']}: "
                                 f"both target {w['shared_paths']}"),
                    )
                    self.board.add_comment(
                        w["story_a"], author="scrum_master",
                        body=(f"⚠️ possible overlap with {w['story_b']}: "
                              f"{w['reason']}. Verify these don't do the same work."),
                    )
                    self.board.add_comment(
                        w["story_b"], author="scrum_master",
                        body=(f"⚠️ possible overlap with {w['story_a']}: "
                              f"{w['reason']}. Verify these don't do the same work."),
                    )
            except Exception as e:
                # Sanity pass is best-effort — never block ingest on it
                self.log(f"decomposition sanity pass failed: {e}")
        except Exception as e:
            reason = f"ingest_failed: {e}"
            self.emitter.emit("goal_ingest_failed", summary=str(e)[:200])
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

            # If READY is non-empty, pull work
            if counts.get("ready", 0) > 0:
                self.log(f"phase=work — ready={counts.get('ready',0)} "
                         f"n_workers={self.n_workers}")
                if self.n_workers <= 1:
                    # Sequential: one worker at a time (the "feels waterfall" mode)
                    pulled = self._work_one()
                    if pulled is None:
                        self.log("phase=work — no worker could pull (starvation)")
                        reason = "no_worker_could_pull"
                        break
                    results.append(pulled)
                    worked += 1
                else:
                    # Parallel: N worker threads race to pull from the ready
                    # queue with a lock. Each worker keeps pulling until either
                    # the ready queue is empty or we hit the story cap.
                    remaining_cap = self.max_stories_worked - worked
                    batch = self._work_parallel(max_stories=remaining_cap)
                    results.extend(batch)
                    worked += len(batch)
                    if not batch:
                        # Nobody could pull anything meaningful (all types starved)
                        reason = "no_worker_could_pull"
                        break
                continue

            # Nothing DRAFT/REFINEMENT/READY left. Done.
            if counts.get("draft", 0) == 0 and counts.get("refinement", 0) == 0 \
               and counts.get("ready", 0) == 0:
                reason = "backlog_empty"
                break

        if not reason:
            reason = f"max_stories_worked ({worked} = cap {self.max_stories_worked})"

        counts = self.board.counts_by_state()
        self.emitter.emit("campaign_finished", reason=reason,
                          stories_done=counts.get("done", 0),
                          stories_blocked=counts.get("blocked", 0),
                          total_tokens=self._total_in + self._total_out,
                          summary=f"stopped: {reason}")

        # Retrospective phase — always runs (Scrum ceremony)
        ended_at_iso = datetime.now(timezone.utc).isoformat()
        try:
            from orgos.agile.retrospective import run_retrospective
            run_retrospective(
                workspace=self.ws,
                board=self.board,
                emitter=self.emitter,
                model=self._model_for("scrum_master"),
                goal=goal,
                reason_stopped=reason,
                started_at=started_at,
                ended_at=ended_at_iso,
                tokens_total=self._total_in + self._total_out,
                token_accumulator=self._accum,
            )
        except Exception as e:
            self.emitter.emit("retro_failed", error=str(e),
                               summary=f"retro raised: {e}")

        # PR publication phase — opt-in via self.open_pr
        pr_url = ""
        if self.open_pr:
            try:
                from orgos.agile.pr_publisher import open_pr_for_team
                pub = open_pr_for_team(self.ws, base=self.pr_base)
                if pub.published:
                    pr_url = pub.pr_url
                    self.emitter.emit("pr_opened", pr_url=pub.pr_url,
                                      summary=f"draft PR: {pub.pr_url}")
                elif pub.error:
                    self.emitter.emit("pr_failed", error=pub.error,
                                      summary=pub.error[:200])
                else:
                    self.emitter.emit("pr_skipped",
                                      reason=pub.skipped_reason,
                                      summary=pub.skipped_reason)
            except Exception as e:
                self.emitter.emit("pr_failed", error=str(e),
                                  summary=f"publisher crashed: {e}")

        return self._final_result(goal, started_at, reason, results=results,
                                    pr_url=pr_url)

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
            self.emitter.emit("refined_ready", story_id=issue_id,
                              points=1, summary="trivial doc — skipped poker")
            return

        # Round 1 of poker (each role uses its own model if configured)
        votes = run_poker_round(
            story=story, board=self.board, model=self.model,
            token_accumulator=self._accum,
            model_for=self._model_for,
        )
        for v in votes:
            self.emitter.emit("poker_vote", story_id=issue_id,
                              voter=v["voter"], points=v["points"],
                              justification=v.get("justification", "")[:200])

        if discussion_needed(votes):
            self.emitter.emit("poker_divergent", story_id=issue_id,
                              votes=[v["points"] for v in votes],
                              summary="votes span >2 Fibonacci steps")
            from orgos.agile.poker import run_discussion_and_revote
            votes = run_discussion_and_revote(
                story=self.board.read(issue_id), board=self.board,
                model=self.model, token_accumulator=self._accum,
                first_votes=votes,
                model_for=self._model_for,
            )
            for v in votes:
                self.emitter.emit("poker_vote", story_id=issue_id,
                                  voter=v["voter"], points=v["points"],
                                  justification=v.get("justification", "")[:200],
                                  round=2)
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
            self.emitter.emit("refined_blocked", story_id=issue_id,
                              summary="still divergent after discussion")
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
            self.emitter.emit("refined_ready", story_id=issue_id,
                              points=story.points,
                              summary=f"agreed on {story.points} pts")
        else:
            missing = required - set(story.signoffs.keys())
            self.board.add_comment(
                issue_id, author="scrum_master",
                body=f"Missing signoffs after poker: {missing}. Blocking.")
            self.board.transition(issue_id, "blocked", actor="scrum_master",
                                   reason=f"missing_signoffs:{missing}")
            self.emitter.emit("refined_blocked", story_id=issue_id,
                              summary=f"missing signoffs: {missing}")

    # ── Phase 3: work ────────────────────────────────────────────────────

    def _work_one(self) -> Optional[WorkResult]:
        """Sequential: try each specialist in turn (used when n_workers=1).

        Returns the WorkResult, or None if no specialist could pull anything.
        """
        for role_name, worker_type in ROLE_TO_PULL_TYPE.items():
            with self._board_lock:
                candidates = self.board.list_ready_for_type(worker_type)
                if not candidates:
                    continue
                story = candidates[0]  # top of priority
                # Optimistically claim by transitioning to in_progress inside the lock
                try:
                    self.board.assign(story.issue_id, role_name)
                    self.board.transition(story.issue_id, "in_progress",
                                          actor=role_name)
                except (InvalidTransition, Exception):
                    continue
            self.emitter.emit("story_pulled", story_id=story.issue_id,
                              worker=role_name, story_type=story.type,
                              points=story.points, title=story.title[:80])
            return self._do_work_and_review_prepared(story, role_name)
        return None

    def _try_claim_next_for(self, role_name: str) -> Optional[Story]:
        """Thread-safe: atomically claim the top READY story for a worker type.

        Returns the Story (already assigned + in_progress on the board), or None
        if nothing is claimable right now.
        """
        worker_type = ROLE_TO_PULL_TYPE[role_name]
        with self._board_lock:
            candidates = self.board.list_ready_for_type(worker_type)
            if not candidates:
                return None
            story = candidates[0]
            try:
                self.board.assign(story.issue_id, role_name)
                self.board.transition(story.issue_id, "in_progress",
                                      actor=role_name)
                return self.board.read(story.issue_id)
            except (InvalidTransition, Exception):
                return None

    def _work_parallel(self, max_stories: int) -> list[WorkResult]:
        """Run n_workers threads pulling from the ready queue concurrently.

        Each thread cycles: try_claim → do_work → repeat, until either the
        ready queue empties for its type or we hit max_stories.
        """
        import concurrent.futures
        results: list[WorkResult] = []
        results_lock = threading.Lock()
        stories_pulled = [0]  # mutable counter shared across threads
        stories_lock = threading.Lock()

        # Build worker plan: N workers, cycling through role types by priority.
        # For n_workers >= 3, one worker per specialist type.
        # For n_workers < 3, pick top-priority types (architect first).
        role_priority = ["architect", "test", "devsecops"]
        # Repeat the priority list if n_workers > 3 so multiple architects can run
        worker_roles = [role_priority[i % len(role_priority)]
                        for i in range(self.n_workers)]

        def _worker_loop(role_name: str, worker_idx: int):
            while True:
                with stories_lock:
                    if stories_pulled[0] >= max_stories:
                        return
                story = self._try_claim_next_for(role_name)
                if story is None:
                    return  # nothing left of this type
                with stories_lock:
                    stories_pulled[0] += 1
                self.emitter.emit("story_pulled",
                                  story_id=story.issue_id,
                                  worker=f"{role_name}#{worker_idx}",
                                  story_type=story.type,
                                  points=story.points,
                                  title=story.title[:80])
                result = self._do_work_and_review_prepared(story, role_name)
                with results_lock:
                    results.append(result)

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=self.n_workers,
            thread_name_prefix="orgos-worker",
        ) as ex:
            futures = [ex.submit(_worker_loop, worker_roles[i], i + 1)
                       for i in range(self.n_workers)]
            for f in concurrent.futures.as_completed(futures):
                try:
                    f.result()
                except Exception as e:
                    self.log(f"worker thread errored: {e}")

        return results

    def _do_work_and_review_prepared(self, story: Story, worker_role: str) -> WorkResult:
        """One story: work, commit, peer-review, DONE (or block).

        Caller must have ALREADY assigned+transitioned to in_progress under
        the board lock (see _try_claim_next_for). This function is safe to
        call from multiple threads concurrently — everything after claim is
        per-story state that lives in the worktree + board (which does its own
        atomic writes).
        """
        # Baseline for this story = current HEAD (racy across concurrent workers,
        # but we're just capturing what the tree looked like when this story
        # started. If another concurrent commit lands, our diff will include it,
        # which is fine — the story is judged on its OWN diff via the envelope's
        # commit_sha, not the diff.
        baseline_sha = self.ws.current_head()

        t0 = time.time()
        result = self._run_work_spawn(story, worker_role, baseline_sha)
        result.wall_seconds = round(time.time() - t0, 2)

        # If a commit landed, transition to REVIEW and run peer review with
        # a bounded rework loop.
        if result.status == "committed" and result.commit_sha:
            self.board.set_commit(story.issue_id, result.commit_sha, actor=worker_role)
            self.board.transition(story.issue_id, "review", actor=worker_role)
            self.emitter.emit("commit_landed", story_id=story.issue_id,
                              commit_sha=result.commit_sha[:7],
                              worker=worker_role,
                              summary=f"{worker_role} committed {result.commit_sha[:7]}")

            passed, concerns = self._peer_review(story.issue_id, exclude_role=worker_role)
            attempt = 1
            MAX_REWORK = 2
            while not passed and attempt <= MAX_REWORK:
                # Send back to in_progress with concerns as new context, then
                # respawn a fix subagent (same worker role).
                self.board.transition(story.issue_id, "in_progress",
                                       actor="reviewer",
                                       reason=f"peer_review_failed (attempt {attempt})")
                self.emitter.emit("story_review_fail", story_id=story.issue_id,
                                  summary=f"attempt {attempt}: {concerns[:200]}")
                pre_rework_sha = self.ws.current_head()
                fix_result = self._run_fix_spawn(
                    story, worker_role, pre_rework_sha, concerns=concerns,
                )
                # Advance HEAD-tracking to the fix commit (if one landed)
                if fix_result.status == "committed" and fix_result.commit_sha:
                    self.board.set_commit(story.issue_id, fix_result.commit_sha,
                                          actor=worker_role)
                    self.emitter.emit("commit_landed", story_id=story.issue_id,
                                      commit_sha=fix_result.commit_sha[:7],
                                      worker=f"{worker_role}(fix#{attempt})",
                                      summary=f"fix attempt {attempt} committed "
                                              f"{fix_result.commit_sha[:7]}")
                    self.board.transition(story.issue_id, "review",
                                          actor=worker_role)
                    passed, concerns = self._peer_review(
                        story.issue_id, exclude_role=worker_role,
                    )
                else:
                    # Fix attempt couldn't produce a commit — bail out to blocked
                    break
                attempt += 1

            if passed:
                current_sha = self.ws.current_head()
                self.board.transition(story.issue_id, "done", actor="reviewer")
                self.emitter.emit("story_review_pass", story_id=story.issue_id,
                                  summary=f"→ DONE ({current_sha[:7]}, "
                                          f"{attempt-1 if attempt>1 else 0} rework attempts)")
            else:
                self.board.transition(story.issue_id, "blocked", actor="reviewer",
                                       reason=f"review_failure_after_{attempt-1}_rework_attempts")
                self.emitter.emit("story_review_fail", story_id=story.issue_id,
                                  summary=f"still failing after {attempt-1} rework attempts")
        elif self._is_noop_completion(result):
            # Architect looked at the story, verified the acceptance criteria
            # are already met, and correctly made no changes. That's a legit
            # DONE state — don't mark it blocked.
            self.board.transition(story.issue_id, "review", actor=worker_role,
                                   reason="noop_no_changes_needed")
            self.board.transition(story.issue_id, "done", actor=worker_role,
                                   reason="noop_no_changes_needed")
            self.board.add_comment(
                story.issue_id, author=worker_role,
                body=f"No-op completion: architect verified acceptance "
                     f"criteria already met — {result.envelope.get('summary', '')}",
            )
            self.emitter.emit("story_done_noop", story_id=story.issue_id,
                              worker=worker_role,
                              summary=result.envelope.get("summary", "")[:150])
        else:
            # No commit AND no self-reported success — actual block.
            self.board.transition(story.issue_id, "blocked", actor=worker_role,
                                   reason="no_commit_produced")
            self.emitter.emit("story_no_commit", story_id=story.issue_id,
                              worker=worker_role,
                              summary=f"{worker_role} produced no commit")

        return result

    def _is_noop_completion(self, result: WorkResult) -> bool:
        """Was this a legitimate 'nothing to do, criteria already met' finish?

        We require ALL of:
          - envelope.status == "completed"
          - envelope.success_criteria_met == True
          - envelope.payload.files_touched is empty or missing
          - envelope.payload.test_passed is True (or no test was needed)
        The last guard prevents an agent from claiming a no-op success when
        it actually failed to verify.
        """
        env = result.envelope or {}
        if not isinstance(env, dict):
            return False
        if env.get("status") != "completed":
            return False
        if not env.get("success_criteria_met"):
            return False
        payload = env.get("payload") or {}
        if not isinstance(payload, dict):
            return False
        files = payload.get("files_touched") or []
        if files:
            return False  # they claim no-op but list files — reject
        test_cmd = (payload.get("test_command") or "").strip()
        if test_cmd and not payload.get("test_passed"):
            return False  # they ran a test and it failed
        return True

    def _run_work_spawn(self, story: Story, worker_role: str,
                        baseline_sha: str) -> WorkResult:
        """Spawn the worker to do the story in the SHARED worktree."""
        from orgos.agile.dispatcher_briefs import build_work_brief
        factory = ROLE_FACTORIES[worker_role]
        role = factory(
            model=self._model_for(worker_role),
            extra_tools=[
                BashTool(default_working_dir=str(self.ws.worktree)),
                ReadFileTool(default_working_dir=str(self.ws.worktree)),
                WriteFileTool(default_working_dir=str(self.ws.worktree)),
                EditFileTool(default_working_dir=str(self.ws.worktree)),
            ],
        )
        role.mcp_servers = [_get_wiki_mcp()]

        brief = build_work_brief(story=story, worktree=self.ws.worktree,
                                   branch=self.ws.manifest().branch,
                                   env=self.env)
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

    def _peer_review(self, issue_id: str, exclude_role: str) -> tuple[bool, str]:
        """Spawn a different specialist to verify the diff.

        Returns (passed, concerns_summary). concerns_summary is a stringified
        list of the reviewer's concerns (joined with "; ") or the review's
        summary, useful as context for a rework attempt.
        """
        candidates = [r for r in ("test", "devsecops", "architect") if r != exclude_role]
        reviewer_role_name = candidates[0]
        story = self.board.read(issue_id)

        from orgos.agile.dispatcher_briefs import build_review_brief
        factory = ROLE_FACTORIES[reviewer_role_name]
        role = factory(
            model=self._model_for(reviewer_role_name),
            extra_tools=[
                BashTool(default_working_dir=str(self.ws.worktree)),
                ReadFileTool(default_working_dir=str(self.ws.worktree)),
                WriteFileTool(default_working_dir=str(self.ws.worktree)),
                EditFileTool(default_working_dir=str(self.ws.worktree)),
            ],
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
            return False, f"review spawn error: {e}"
        self._accum(r)

        for to in r.tasks_output:
            raw = getattr(to, "raw", "") or ""
            for blob in _extract_json_objects(raw):
                try:
                    data = json.loads(blob)
                except json.JSONDecodeError:
                    continue
                if isinstance(data, dict):
                    verdict = str(data.get("review", data.get("verdict", ""))).lower()
                    summary = str(data.get("summary", ""))
                    payload = data.get("payload") or {}
                    concerns_list = payload.get("concerns") or []
                    concerns_str = "; ".join(str(c) for c in concerns_list) if concerns_list else summary
                    if verdict in ("pass", "approve", "approved", "ok"):
                        self.board.add_comment(
                            issue_id, author=f"{reviewer_role_name}_reviewer",
                            body=f"Review PASS: {summary}"
                                 + (f" | concerns: {concerns_str}" if concerns_str else ""))
                        return True, concerns_str
                    if verdict in ("fail", "reject", "rejected", "block"):
                        self.board.add_comment(
                            issue_id, author=f"{reviewer_role_name}_reviewer",
                            body=f"Review FAIL: {summary}"
                                 + (f" | concerns: {concerns_str}" if concerns_str else ""))
                        return False, concerns_str or summary or "reviewer failed the story"

        self.log(f"    review {issue_id}: no verdict emitted, defaulting PASS")
        return True, ""

    def _run_fix_spawn(self, story: Story, worker_role: str,
                        baseline_sha: str, concerns: str) -> WorkResult:
        """Respawn the worker to fix reviewer concerns.

        Same role as the original author. Builds a fix brief that includes the
        reviewer's concerns as new context.
        """
        from orgos.agile.dispatcher_briefs import build_work_brief
        factory = ROLE_FACTORIES[worker_role]
        role = factory(
            model=self._model_for(worker_role),
            extra_tools=[
                BashTool(default_working_dir=str(self.ws.worktree)),
                ReadFileTool(default_working_dir=str(self.ws.worktree)),
                WriteFileTool(default_working_dir=str(self.ws.worktree)),
                EditFileTool(default_working_dir=str(self.ws.worktree)),
            ],
        )
        role.mcp_servers = [_get_wiki_mcp()]

        # Augment the work brief with reviewer concerns as new context
        original = build_work_brief(story=story, worktree=self.ws.worktree,
                                      branch=self.ws.manifest().branch)
        fix_objective = (
            "REWORK — a peer reviewer just failed your prior commit on this "
            "story. Concerns to address:\n\n"
            f"  {concerns}\n\n"
            "Read the diff you just committed (`git diff HEAD~1`), fix the "
            "concerns above, run tests, and commit AGAIN. The new commit "
            "will REPLACE your prior work in the review cycle. Emit a fresh "
            "envelope reflecting the NEW commit.\n\n"
            "─────────── ORIGINAL BRIEF FOLLOWS ───────────\n\n"
            f"{original.objective}"
        )
        from orgos.spawn import TaskBrief
        fix_brief = TaskBrief(
            objective=fix_objective,
            expected_output=original.expected_output,
            success_criteria=original.success_criteria + ["Addresses reviewer concerns."],
            inputs=original.inputs,
        )
        try:
            r = spawn(role, fix_brief, run_budget_tokens=1_500_000)
        except Exception as e:
            return WorkResult(
                story_id=story.issue_id, role=worker_role,
                status="failed", error=f"{type(e).__name__}: {e}",
            )
        tin, tout = self._accum(r)

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

        head = self.ws.current_head()
        if head and head != baseline_sha:
            diff_stat = self.ws.diff_since(baseline_sha, stat_only=True)
            return WorkResult(
                story_id=story.issue_id, role=f"{worker_role}(fix)",
                status="committed", commit_sha=head,
                diff_summary=diff_stat[:2000], envelope=envelope,
                tokens_input=tin, tokens_output=tout,
            )
        return WorkResult(
            story_id=story.issue_id, role=f"{worker_role}(fix)",
            status="no_commit", envelope=envelope,
            tokens_input=tin, tokens_output=tout,
        )

    # ── Final ────────────────────────────────────────────────────────────

    def _final_result(self, goal: str, started_at: str, reason: str,
                       results: list[WorkResult] | None = None,
                       pr_url: str = "") -> DispatchResult:
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
            pr_url=pr_url,
        )

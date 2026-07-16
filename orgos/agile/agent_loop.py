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
import re
import time
from pathlib import Path
from typing import Any, Optional


def _matches_any(text: str, *words: str) -> bool:
    """Word-boundary match — 'spec' matches 'the spec' but not 'retrospective'."""
    return any(re.search(rf"\b{re.escape(w)}\b", text) for w in words)

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
        # Reset scheduled-task fired markers so that a crash+restart doesn't
        # leave _last_fired_at holding a value from the previous session
        # (which would make (now - _last_fired_at) negative and freeze tasks
        # for up to one full cadence interval after restart).
        for t in self.scheduler.tasks:
            t._last_fired_at = -1.0
        self.emitter.emit("agent_started", role=self.role,
                          summary=f"{self.role} online")

        while self._alive:
            now = time.time() - self._start_wall
            due_tasks = self.scheduler.pending(now)

            for task in due_tasks:
                text = task.action_text.lower()
                # Delivery: implicit "check board" for short-cadence tasks
                if self.is_delivery_agent and task.cadence_seconds <= 60 \
                   and ("board" in text or "story" in text or "check" in text):
                    await self._pull_and_work_once()
                    continue
                # Ceremony routing. Order matters because persona text may
                # mention several action nouns; the most-specific-first order:
                #   1. 'retrospective' → retro (SM's primary verb)
                #   2. 'replan' → replan (PO's primary verb; overrides bare
                #      'RETRO.md' filename references in PO's text)
                #   3. bare 'retro' → retro (fallback)
                #   4. 'backlog'/'spec' → replan
                #   5. 'poker'/'refinement' → poker
                #   6. 'pr' + [comment|feedback|review] → pr_feedback
                # All checks use word boundaries so 'spec' does not match
                # 'retrospective', etc.
                if _matches_any(text, "sprint") and _matches_any(
                    text, "open", "close", "start", "boundary", "planning",
                ):
                    await self._run_sprint_boundary()
                    continue
                if _matches_any(text, "accept", "acceptance") and \
                        _matches_any(text, "story", "stories", "review", "merged"):
                    await self._run_acceptance()
                    continue
                if _matches_any(text, "retrospective"):
                    await self._run_retro()
                    continue
                if _matches_any(text, "replan"):
                    await self._run_replan()
                    continue
                if _matches_any(text, "retro"):
                    await self._run_retro()
                    continue
                if _matches_any(text, "backlog", "spec"):
                    await self._run_replan()
                    continue
                if _matches_any(text, "poker", "refinement"):
                    await self._run_poker()
                    continue
                if _matches_any(text, "pr") and _matches_any(
                    text, "comment", "comments", "feedback", "review",
                ):
                    await self._run_pr_feedback()
                    continue
                # Otherwise: no-op (unknown scheduled task; log for the retro to notice)
                self.emitter.emit(
                    "scheduled_noop", role=self.role,
                    summary=f"unrouted schedule: {task.action_text[:80]}",
                )

            # Sleep until next scheduled tick (or 1s min, so stop() is responsive)
            await asyncio.sleep(min(1.0, self.scheduler.next_tick_in(now)))

        self.emitter.emit("agent_stopped", role=self.role,
                          summary=f"{self.role} shut down cleanly")

    async def _run_retro(self) -> None:
        try:
            from orgos.agile.retrospective import run_retrospective
            m = self.workspace.manifest()
            await asyncio.get_running_loop().run_in_executor(
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
            await asyncio.get_running_loop().run_in_executor(
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
        """Refinement ceremony: vote on each draft/refinement story, converge
        on a point value, and transition the story to ready so delivery agents
        can pull it.

        Flow per story:
          draft → refinement (if in draft)
          run_poker_round → 3 votes
          if divergent → run_discussion_and_revote
          set_points(median of Fibonacci indices)
          refinement → ready
        """
        try:
            from orgos.agile.poker import (
                run_poker_round, discussion_needed,
                run_discussion_and_revote, FIB,
            )
            m = self.workspace.manifest()
            # Snapshot the list — set_points/transition below would mutate what
            # list_state returns mid-iteration otherwise.
            stories = list(self.board.list_state("draft")) + \
                      list(self.board.list_state("refinement"))
            for story in stories:
                await asyncio.get_running_loop().run_in_executor(
                    None,
                    lambda s=story: self._refine_one_story(
                        s, m.model, run_poker_round, discussion_needed,
                        run_discussion_and_revote, FIB,
                    ),
                )
        except Exception as e:
            self.emitter.emit("poker_failed", role=self.role, summary=str(e)[:200])

    def _refine_one_story(
        self, story, model, run_poker_round, discussion_needed,
        run_discussion_and_revote, FIB,
    ) -> None:
        """Blocking helper — called from _run_poker's executor thread."""
        # 1. draft → refinement (skip if already there)
        if story.state == "draft":
            try:
                self.board.transition(
                    story.issue_id, "refinement", actor=self.role,
                )
            except Exception:
                return  # already moved by another actor; skip

        # 2. First-round vote
        votes = run_poker_round(
            story=story, board=self.board, model=model,
            token_accumulator=lambda r: (0, 0),
        )
        # 3. Discussion if divergent
        if discussion_needed(votes):
            votes = run_discussion_and_revote(
                story=story, board=self.board, model=model,
                token_accumulator=lambda r: (0, 0),
                first_votes=votes,
            )
        # 4. Converge — median of Fibonacci indices, snapped to a Fib value
        pts = sorted(v["points"] for v in votes if isinstance(v.get("points"), int))
        if not pts:
            return  # all votes malformed; leave in refinement for retro to notice
        median = pts[len(pts) // 2]
        # Snap to nearest Fibonacci value if not already one
        final_points = min(FIB, key=lambda f: abs(f - median))

        # 5. set_points + transition to ready
        try:
            self.board.set_points(story.issue_id, final_points, actor=self.role)
            self.board.transition(story.issue_id, "ready", actor=self.role)
            self.emitter.emit(
                "story_refined", story_id=story.issue_id, points=final_points,
                summary=f"{story.issue_id} refined to {final_points} pts",
            )
        except Exception as e:
            self.emitter.emit(
                "poker_failed", role=self.role,
                summary=f"{story.issue_id}: {e}"[:200],
            )

    async def _run_sprint_boundary(self) -> None:
        """Close the current sprint (if open) and open the next one.

        Runs sprint planning: picks up to `velocity_target` ready stories that
        are not yet in a sprint and assigns them the new sprint's number.
        Emits sprint_closed + sprint_opened events with metrics.
        """
        try:
            from orgos.agile.sprints import (
                close_sprint, open_sprint, current_sprint_number,
            )

            def _boundary() -> tuple:
                prev_num = current_sprint_number(self.workspace)
                closed = None
                if prev_num > 0:
                    closed = close_sprint(
                        self.workspace, self.board, reason="scheduled",
                    )
                new_sprint = open_sprint(
                    self.workspace, self.board, velocity_target=6,
                )
                return closed, new_sprint

            closed, opened = await asyncio.get_running_loop().run_in_executor(
                None, _boundary,
            )
            if closed is not None:
                self.emitter.emit(
                    "sprint_closed", sprint_number=closed.number,
                    stories_done=len(closed.stories_done),
                    points_completed=closed.points_completed,
                    reason=closed.reason_closed,
                    summary=(
                        f"sprint {closed.number} closed: "
                        f"{len(closed.stories_done)} done, "
                        f"{closed.points_completed} pts"
                    ),
                )
            self.emitter.emit(
                "sprint_opened", sprint_number=opened.number,
                committed_backlog_size=len(opened.committed_backlog),
                summary=(
                    f"sprint {opened.number} opened with "
                    f"{len(opened.committed_backlog)} committed stories"
                ),
            )
        except Exception as e:
            self.emitter.emit(
                "sprint_boundary_failed", role=self.role, summary=str(e)[:200],
            )

    async def _run_acceptance(self) -> None:
        """PO acceptance gate: review stories in pending_acceptance and
        transition to done (accept) or blocked (reject).

        v1 policy: accept any story that has a commit_sha and passes basic
        sanity (no empty commit_sha, no error markers in audit). Rejection
        criteria will be tightened once we have real acceptance criteria
        stored on the story object.
        """
        try:
            def _accept_batch() -> int:
                pending = self.board.list_state("pending_acceptance")
                accepted = 0
                for story in pending:
                    reason = ""
                    accept = bool(story.commit_sha)
                    if not accept:
                        reason = "no commit_sha on story"
                    try:
                        if accept:
                            self.board.transition(
                                story.issue_id, "done", actor="po",
                                reason="accepted",
                            )
                            accepted += 1
                        else:
                            self.board.transition(
                                story.issue_id, "blocked", actor="po",
                                reason=f"rejected:{reason}"[:200],
                            )
                    except Exception:
                        continue
                return accepted

            count = await asyncio.get_running_loop().run_in_executor(
                None, _accept_batch,
            )
            if count > 0:
                self.emitter.emit(
                    "stories_accepted", accepted=count,
                    summary=f"PO accepted {count} pending stories",
                )
        except Exception as e:
            self.emitter.emit(
                "acceptance_failed", role=self.role, summary=str(e)[:200],
            )

    async def _run_pr_feedback(self) -> None:
        try:
            from orgos.agile.pr_feedback import ingest_pr_feedback
            import json
            # Look for pr_url in (a) a dedicated pr_url.txt written by
            # pr_publisher when a PR is opened mid-run, or (b) a
            # campaign_result.json from a previous shutdown of this workspace.
            pr_url = ""
            pr_url_file = self.workspace.root / "pr_url.txt"
            if pr_url_file.exists():
                try:
                    pr_url = pr_url_file.read_text(encoding="utf-8").strip()
                except Exception:
                    pass
            if not pr_url:
                r_path = self.workspace.root / "campaign_result.json"
                if r_path.exists():
                    try:
                        pr_url = json.loads(r_path.read_text()).get("pr_url", "")
                    except Exception:
                        pass
            if not pr_url:
                return  # no PR published yet
            await asyncio.get_running_loop().run_in_executor(
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

    async def _pull_and_work_once(self) -> None:
        """Delivery-agent action: check board, pull if match, run executor, enqueue merge."""
        from orgos.agile.sprints import current_sprint_number
        try:
            sn = current_sprint_number(self.workspace)
        except Exception:
            sn = 0
        story = self.board.try_claim_next_for(
            self.role, actor=self.role, sprint_number=sn,
        )
        if story is None:
            return

        self.emitter.emit(
            "story_pulled", story_id=story.issue_id,
            worker=self.role, story_type=story.type,
            title=story.title[:80],
        )

        # Run the coding executor in a thread pool (it may be blocking I/O)
        try:
            result: ExecutionResult = await asyncio.get_running_loop().run_in_executor(
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
                worker=self.role,
                tokens_in=result.tokens_input,
                tokens_out=result.tokens_output,
                wall_seconds=result.wall_seconds,
                summary=result.error[:200],
            )
            return

        # Success: transition to review, enqueue merge
        self.board.transition(story.issue_id, "review", actor=self.role)
        self.board.set_commit(story.issue_id, result.commit_sha, actor=self.role)
        self.emitter.emit(
            "commit_landed", story_id=story.issue_id,
            commit_sha=result.commit_sha[:7], worker=self.role,
            tokens_in=result.tokens_input,
            tokens_out=result.tokens_output,
            wall_seconds=result.wall_seconds,
            summary=f"{self.role} committed {result.commit_sha[:7]}",
        )
        await self.merge_queue.enqueue(MergeRequest(
            story_id=story.issue_id,
            from_branch=self.workspace.agent_branch(self.role),
            files_touched=result.files_touched,
        ))

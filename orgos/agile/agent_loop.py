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
        try:
            from orgos.agile.poker import run_poker_round
            m = self.workspace.manifest()
            for state in ("draft", "refinement"):
                for story in self.board.list_state(state):
                    await asyncio.get_running_loop().run_in_executor(
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
        story = self.board.try_claim_next_for(self.role, actor=self.role)
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

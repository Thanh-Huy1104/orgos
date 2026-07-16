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

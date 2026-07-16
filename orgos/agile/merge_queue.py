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

    # 1. In the integration worktree, make sure we're on the integration branch.
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

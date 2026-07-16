"""FIFO merge queue with rebase-before-merge. Serializes cross-worktree git.

Agents enqueue a MergeRequest after completing a story. A single MergeWorker
async task drains the queue, taking a global git_op_lock for each merge.

Merge sequence (§5 spec — linear integration history):
  1. In the SOURCE repo: rebase from_branch onto the integration branch.
     On rebase conflict → abort and transition story to blocked.
  2. In the INTEGRATION worktree: checkout the integration branch.
  3. Fast-forward-only merge of from_branch into integration.

On conflict: transitions story to blocked with reason 'merge_conflict:<stderr>'.
"""

from __future__ import annotations

import asyncio
import subprocess
from dataclasses import dataclass, field
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


def _run_git(args: list[str], cwd: Any, timeout: int = 60) -> tuple[int, str, str]:
    r = subprocess.run(
        ["git", *args], cwd=str(cwd),
        capture_output=True, text=True, timeout=timeout,
    )
    return r.returncode, (r.stdout or ""), (r.stderr or "")


def _attempt_merge(
    workspace: Any, from_branch: str,
) -> tuple[bool, str]:
    """Rebase from_branch onto integration branch, then fast-forward integration.

    Sequence (§5 spec — keeps integration history linear):
      1. In the AGENT worktree that already has from_branch checked out:
         `git rebase <integration_branch>`. On failure: abort rebase and
         return (False, 'merge_conflict:<err>').

         (We cannot rebase in the source repo — the branch is already
         checked out in the agent worktree, and git refuses to check out
         the same branch in a second place.)

      2. In INTEGRATION worktree: `git checkout <integration_branch>`,
         then `git merge --ff-only <from_branch>`. Fast-forward is
         guaranteed after a clean rebase.

    Returns (ok, message_or_error).
    """
    integ = workspace.integration_worktree
    integ_branch = workspace.integration_branch

    # from_branch is 'team/<team_id>/agent/<role>' → role is the last segment
    role = from_branch.rsplit("/", 1)[-1]
    try:
        agent_worktree = workspace.agent_worktree(role)
    except Exception as e:
        return False, f"merge_setup:cannot resolve agent worktree for {role}: {e}"

    # 1. Rebase inside the agent's worktree (where from_branch is checked out).
    rc, out, err = _run_git(["rebase", integ_branch], agent_worktree)
    if rc != 0:
        _run_git(["rebase", "--abort"], agent_worktree)
        return False, f"merge_conflict:{err.strip() or out.strip()}"

    # 2. Fast-forward integration onto from_branch's new tip.
    rc, out, err = _run_git(["checkout", integ_branch], integ)
    if rc != 0:
        return False, f"checkout integration: {err.strip()}"

    rc, out, err = _run_git(["merge", "--ff-only", from_branch], integ)
    if rc == 0:
        return True, "merged clean"

    return False, f"merge_ff_failed:{err.strip() or out.strip()}"


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
            ok, msg = await asyncio.get_running_loop().run_in_executor(
                None, _attempt_merge, workspace, request.from_branch,
            )

        if ok:
            try:
                board.transition(request.story_id, "done", actor="merge_worker")
            except Exception as e:
                emitter.emit(
                    "merge_state_error", story_id=request.story_id,
                    summary=f"failed to transition to done: {e}",
                )
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
            except Exception as e:
                emitter.emit(
                    "merge_state_error", story_id=request.story_id,
                    summary=f"failed to transition to blocked: {e}",
                )
            emitter.emit(
                "merge_conflict", story_id=request.story_id,
                branch=request.from_branch, summary=msg[:200],
            )

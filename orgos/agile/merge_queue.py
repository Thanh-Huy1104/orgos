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
    *, resolve_llm: bool = True, model: str = "deepseek/deepseek-chat",
) -> tuple[bool, str]:
    """Rebase from_branch onto integration branch, then fast-forward integration.

    Sequence (§5 spec — keeps integration history linear):
      1. In the AGENT worktree that already has from_branch checked out:
         `git rebase <integration_branch>`.
         On failure: try LLM-driven auto-resolution (Fix §B6) for safe
         file classes (__init__.py, markdown, test files). If resolution
         succeeds → `git rebase --continue` and proceed. Otherwise:
         abort + reset agent branch to integ HEAD, return merge_conflict.
      2. In INTEGRATION worktree: `git checkout <integration_branch>`,
         then `git merge --ff-only <from_branch>`. Fast-forward is
         guaranteed after a clean rebase.

    Returns (ok, message_or_error).
    """
    integ = workspace.integration_worktree
    integ_branch = workspace.integration_branch

    # from_branch is 'team/<team_id>/agent/<role>[-<instance>]'.
    # The last segment is either '<role>' (instance 0) or '<role>-<N>' for
    # N>0 delivery-agent instances. Split to recover both.
    last = from_branch.rsplit("/", 1)[-1]
    if "-" in last and last.rsplit("-", 1)[-1].isdigit():
        role, inst_str = last.rsplit("-", 1)
        instance = int(inst_str)
    else:
        role, instance = last, 0
    try:
        agent_worktree = workspace.agent_worktree(role, instance)
    except TypeError:
        # Older workspace mock in tests may not accept instance kwarg
        agent_worktree = workspace.agent_worktree(role)
    except Exception as e:
        return False, f"merge_setup:cannot resolve agent worktree for {last}: {e}"

    # 1. Rebase inside the agent's worktree (where from_branch is checked out).
    # --autostash: if the worktree has uncommitted changes (from a next-story
    # executor call already writing files in the same worktree, common at
    # N>1 dev agents), stash them before rebasing and re-apply after.
    rc, out, err = _run_git(
        ["rebase", "--autostash", integ_branch], agent_worktree,
    )
    if rc != 0:
        # Fix §B6 — before aborting, try LLM-driven auto-resolution for
        # safe file classes (init.py, markdown, test files). Only kicks
        # in when resolve_llm=True (default) and every conflicted file
        # passes the safety gate.
        resolved_by_llm = False
        resolve_note = ""
        if resolve_llm:
            try:
                from orgos.agile.merge_resolver import try_resolve_rebase_conflicts
                ok, msg = try_resolve_rebase_conflicts(
                    agent_worktree, model=model,
                )
                if ok:
                    rc2, out2, err2 = _run_git(
                        ["-c", "core.editor=true", "rebase", "--continue"],
                        agent_worktree, timeout=30,
                    )
                    if rc2 == 0:
                        resolved_by_llm = True
                        resolve_note = f"llm_resolved:{msg}"
                    else:
                        # LLM resolution didn't clear rebase — abort
                        _run_git(["rebase", "--abort"], agent_worktree)
                        resolve_note = f"llm_resolve_ok_but_continue_failed:{err2[:100]}"
                else:
                    resolve_note = f"llm_declined:{msg}"
            except Exception as e:
                resolve_note = f"llm_resolver_error:{e}"[:200]

        if not resolved_by_llm:
            _run_git(["rebase", "--abort"], agent_worktree)
            # RESET AGENT BRANCH TO INTEGRATION HEAD (cascade fix from §J).
            _run_git(["reset", "--hard", integ_branch], agent_worktree)
            base_msg = err.strip() or out.strip()
            if resolve_note:
                return False, f"merge_conflict:{base_msg} [{resolve_note[:100]}]"
            return False, f"merge_conflict:{base_msg}"

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
    resolve_llm: bool = True,
    model: str = "deepseek/deepseek-chat",
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
                None,
                lambda: _attempt_merge(
                    workspace, request.from_branch,
                    resolve_llm=resolve_llm, model=model,
                ),
            )
            if "llm_resolved:" in msg:
                try:
                    emitter.emit(
                        "merge_llm_resolved", story_id=request.story_id,
                        branch=request.from_branch, summary=msg,
                    )
                except Exception:
                    pass

        if ok:
            try:
                # Handoff to PO acceptance gate (real Scrum DoD) — story is
                # NOT done until PO accepts. PO's heartbeat runs the
                # acceptance ceremony and transitions to done or blocked.
                board.transition(
                    request.story_id, "pending_acceptance",
                    actor="merge_worker",
                )
            except Exception as e:
                emitter.emit(
                    "merge_state_error", story_id=request.story_id,
                    summary=f"failed to transition to pending_acceptance: {e}",
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

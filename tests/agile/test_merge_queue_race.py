"""Race-condition tests for merge queue at N>1.

These validate the fix that landed in commit 76449fd (--autostash) and the
branch-reset-on-conflict cascade unblocker. Both tests use REAL git worktrees
because the race is a git-worktree behavior, not something a mock captures.
"""

from __future__ import annotations

import asyncio
import subprocess
from unittest.mock import MagicMock

import pytest

from orgos.agile.board_store import BoardStore
from orgos.agile.live_events import EventEmitter
from orgos.agile.merge_queue import (
    MergeQueue, MergeRequest, run_merge_worker,
)


@pytest.fixture
def two_agent_repo(tmp_path):
    """Repo with an integration branch + two separate agent worktrees.
    Simulates the N>1 shape where architect and architect#1 both push
    commits touching different files."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("init")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)
    subprocess.run(["git", "branch", "integration"], cwd=tmp_path, check=True)

    # Two agent worktrees, each on its own branch, each with a commit on a
    # DIFFERENT file (so we're testing merge-queue race, not conflict).
    wt_a = tmp_path / "wt_a"
    wt_b = tmp_path / "wt_b"
    subprocess.run(
        ["git", "worktree", "add", "-b", "agent/arch", str(wt_a), "integration"],
        cwd=tmp_path, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "worktree", "add", "-b", "agent/arch-1", str(wt_b), "integration"],
        cwd=tmp_path, check=True, capture_output=True,
    )
    (wt_a / "alpha.py").write_text("alpha\n")
    subprocess.run(["git", "add", "-A"], cwd=wt_a, check=True)
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t",
         "commit", "-qm", "arch commit"], cwd=wt_a, check=True,
    )
    (wt_b / "beta.py").write_text("beta\n")
    subprocess.run(["git", "add", "-A"], cwd=wt_b, check=True)
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t",
         "commit", "-qm", "arch-1 commit"], cwd=wt_b, check=True,
    )
    return {"repo": tmp_path, "wt_a": wt_a, "wt_b": wt_b}


class TestConcurrentMergesDifferentFiles:
    """Two agents commit to different files. Both should land clean —
    merge queue is FIFO and each rebase should succeed."""

    def test_both_land_when_files_disjoint(self, two_agent_repo, tmp_path):
        repo = two_agent_repo["repo"]
        wt_a = two_agent_repo["wt_a"]
        wt_b = two_agent_repo["wt_b"]

        board = BoardStore(tmp_path / "board")
        for sid, comp in (("SA", "alpha"), ("SB", "beta")):
            board.draft_story(
                issue_id=sid, title=sid, body="b", story_type="feature",
                files_to_touch=[f"{comp}.py"],
            )
            board.transition(sid, "refinement", actor="sm")
            board.transition(sid, "ready", actor="sm")
            board.transition(sid, "in_progress", actor="arch")
            board.transition(sid, "review", actor="arch")

        ws = MagicMock()
        ws.integration_worktree = repo
        ws.integration_branch = "integration"
        ws.source_repo = repo
        # agent_worktree(role, instance=0) returns the right worktree
        ws.agent_worktree = lambda role, instance=0: (
            wt_a if instance == 0 else wt_b
        )
        emitter = EventEmitter(tmp_path)
        queue = MergeQueue(workspace=ws)

        async def scenario():
            await queue.enqueue(MergeRequest(
                story_id="SA", from_branch="agent/arch",
                files_touched=["alpha.py"],
            ))
            await queue.enqueue(MergeRequest(
                story_id="SB", from_branch="agent/arch-1",
                files_touched=["beta.py"],
            ))
            worker = asyncio.create_task(run_merge_worker(
                queue, ws, board, emitter, stop_when_empty=True,
            ))
            await asyncio.wait_for(worker, timeout=15.0)

        asyncio.run(scenario())

        # Both should have landed (integration branch is on the merge target).
        assert board.read("SA").state == "pending_acceptance"
        assert board.read("SB").state == "pending_acceptance"


class TestAutostashOnUncommittedChanges:
    """Regression for the N>1 race: while the merge worker is rebasing
    agent branch A, agent A's *next* story has already started writing to
    the same worktree. Without --autostash, rebase aborts. With, it works."""

    def test_rebase_survives_uncommitted_worktree_changes(
        self, two_agent_repo, tmp_path,
    ):
        repo = two_agent_repo["repo"]
        wt_a = two_agent_repo["wt_a"]

        # Simulate: agent has already started next story — uncommitted junk
        # in the worktree at the moment the merge worker tries to rebase.
        (wt_a / "in_progress_scratch.py").write_text("# uncommitted, mid-write\n")

        board = BoardStore(tmp_path / "board")
        board.draft_story(
            issue_id="SA", title="SA", body="b", story_type="feature",
            files_to_touch=["alpha.py"],
        )
        board.transition("SA", "refinement", actor="sm")
        board.transition("SA", "ready", actor="sm")
        board.transition("SA", "in_progress", actor="arch")
        board.transition("SA", "review", actor="arch")

        ws = MagicMock()
        ws.integration_worktree = repo
        ws.integration_branch = "integration"
        ws.source_repo = repo
        ws.agent_worktree = lambda role, instance=0: wt_a
        emitter = EventEmitter(tmp_path)
        queue = MergeQueue(workspace=ws)

        async def scenario():
            await queue.enqueue(MergeRequest(
                story_id="SA", from_branch="agent/arch",
                files_touched=["alpha.py"],
            ))
            worker = asyncio.create_task(run_merge_worker(
                queue, ws, board, emitter, stop_when_empty=True,
            ))
            await asyncio.wait_for(worker, timeout=10.0)

        asyncio.run(scenario())

        # Merge should have completed (autostashed) rather than blocking.
        assert board.read("SA").state == "pending_acceptance"
        # And the scratch file should still be present (autostash reapplied it).
        assert (wt_a / "in_progress_scratch.py").exists()

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
        # In this single-repo fixture, the "agent worktree" is the same path;
        # the branch is already checked out here (see team_repo fixture below).
        ws.agent_worktree = lambda role: team_repo

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
        # Merge worker hands off to PO acceptance gate — story is
        # pending_acceptance, not done, until PO's ceremony accepts it.
        assert board.read("S1").state == "pending_acceptance"


class TestMergeWorkerConflict:
    def test_transitions_to_blocked_on_conflict(self, team_repo, tmp_path):
        # Put agent/arch into its own worktree (like production layout).
        agent_wt = tmp_path / "agent_wt"
        subprocess.run(
            ["git", "worktree", "add", str(agent_wt), "agent/arch"],
            cwd=team_repo, check=True, capture_output=True,
        )

        # Create a conflicting change on integration branch (in team_repo,
        # which is on integration).
        subprocess.run(["git", "checkout", "integration"], cwd=team_repo, check=True)
        (team_repo / "app.py").write_text("integration side\n")
        subprocess.run(["git", "add", "-A"], cwd=team_repo, check=True)
        subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@t",
             "commit", "-qm", "integration change"],
            cwd=team_repo, check=True,
        )
        # agent/arch (in agent_wt) already wrote "hello\n" to app.py; rebase
        # will conflict with integration's version.

        board = BoardStore(tmp_path / "board")
        board.draft_story(issue_id="S1", title="t", body="b",
                          story_type="feature", files_to_touch=["app.py"])
        board.transition("S1", "refinement", actor="sm")
        board.transition("S1", "ready", actor="sm")
        board.transition("S1", "in_progress", actor="arch")
        board.transition("S1", "review", actor="arch")

        ws = MagicMock()
        ws.integration_worktree = team_repo
        ws.integration_branch = "integration"
        ws.source_repo = team_repo
        ws.agent_worktree = lambda role: agent_wt

        emitter = EventEmitter(tmp_path)
        queue = MergeQueue(workspace=ws)

        async def scenario():
            await queue.enqueue(MergeRequest(
                story_id="S1", from_branch="agent/arch",
                files_touched=["app.py"],
            ))
            worker = asyncio.create_task(run_merge_worker(
                queue, ws, board, emitter, stop_when_empty=True,
            ))
            await asyncio.wait_for(worker, timeout=10.0)

        asyncio.run(scenario())

        story = board.read("S1")
        assert story.state == "blocked"
        # reason is stored in the audit trail, not on the story object
        audit = board.audit_trail("S1")
        transition_entry = next(
            (e for e in reversed(audit)
             if e.get("action") == "transition" and e.get("to_state") == "blocked"),
            None,
        )
        assert transition_entry is not None, "No blocked transition found in audit"
        assert transition_entry.get("reason", "").startswith("merge_conflict:")


class TestMergeWorkerBranchResetOnConflict:
    """Regression for the cascade seen in smoke #3: a single un-rebasable
    commit on an agent branch was blocking all subsequent commits because
    rebase kept failing on the same first commit. Fix: reset the agent
    branch to integration HEAD after a failed rebase, so future commits
    have a clean base."""

    def test_agent_branch_resets_after_failed_rebase(self, team_repo, tmp_path):
        # Put agent/arch into its own worktree with a conflicting commit
        agent_wt = tmp_path / "agent_wt"
        subprocess.run(
            ["git", "worktree", "add", str(agent_wt), "agent/arch"],
            cwd=team_repo, check=True, capture_output=True,
        )
        # Diverge integration branch
        subprocess.run(["git", "checkout", "integration"], cwd=team_repo, check=True)
        (team_repo / "app.py").write_text("integration side\n")
        subprocess.run(["git", "add", "-A"], cwd=team_repo, check=True)
        subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@t",
             "commit", "-qm", "integration change"],
            cwd=team_repo, check=True,
        )

        board = BoardStore(tmp_path / "board")
        board.draft_story(issue_id="S1", title="t", body="b",
                          story_type="feature", files_to_touch=["app.py"])
        board.transition("S1", "refinement", actor="sm")
        board.transition("S1", "ready", actor="sm")
        board.transition("S1", "in_progress", actor="arch")
        board.transition("S1", "review", actor="arch")

        ws = MagicMock()
        ws.integration_worktree = team_repo
        ws.integration_branch = "integration"
        ws.source_repo = team_repo
        ws.agent_worktree = lambda role: agent_wt

        emitter = EventEmitter(tmp_path)
        queue = MergeQueue(workspace=ws)

        async def scenario():
            await queue.enqueue(MergeRequest(
                story_id="S1", from_branch="agent/arch",
                files_touched=["app.py"],
            ))
            worker = asyncio.create_task(run_merge_worker(
                queue, ws, board, emitter, stop_when_empty=True,
            ))
            await asyncio.wait_for(worker, timeout=10.0)

        asyncio.run(scenario())

        # Story is blocked (expected) — but agent branch should now match
        # integration HEAD (RESET FIX), so future commits will have a
        # clean base.
        assert board.read("S1").state == "blocked"
        agent_head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=agent_wt,
            capture_output=True, text=True,
        ).stdout.strip()
        integ_head = subprocess.run(
            ["git", "rev-parse", "integration"], cwd=team_repo,
            capture_output=True, text=True,
        ).stdout.strip()
        assert agent_head == integ_head, (
            f"Agent branch not reset to integration HEAD after rebase failure. "
            f"agent={agent_head[:7]}, integ={integ_head[:7]}. "
            f"This means the un-rebasable commit is still on the branch → "
            f"cascade failure on next rebase."
        )

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
        assert board.read("S1").state == "done"

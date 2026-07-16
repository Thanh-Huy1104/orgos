"""Tests for AsyncAgent — the async runtime per role."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

import pytest

from orgos.agile.agent_loop import AsyncAgent
from orgos.agile.board_store import BoardStore
from orgos.agile.coding_executor import ExecutionResult
from orgos.agile.live_events import EventEmitter
from orgos.agile.merge_queue import MergeQueue, MergeRequest


@pytest.fixture
def real_repo(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("init")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)
    return tmp_path


def _make_ws(root: Path, integration: Path):
    ws = MagicMock()
    ws.root = root
    ws.integration_worktree = integration
    ws.integration_branch = "master"
    ws.agent_worktree = lambda role: integration
    ws.agent_branch = lambda role: "master"
    return ws


class TestAsyncAgentDelivery:
    def test_pulls_and_works_a_story(self, tmp_path, real_repo, monkeypatch):
        board = BoardStore(tmp_path / "board")
        board.draft_story(issue_id="S1", title="t", body="b",
                          story_type="architecture", files_to_touch=[])
        board.transition("S1", "refinement", actor="sm")
        board.transition("S1", "ready", actor="sm")

        ws = _make_ws(tmp_path, real_repo)
        emitter = EventEmitter(tmp_path)
        queue = MergeQueue(ws)

        executor = MagicMock()
        executor.run_story = MagicMock(return_value=ExecutionResult(
            success=True, commit_sha="abc1234",
            files_touched=["app.py"], learnings="did the thing",
        ))

        heartbeat_md = "## Every 1 seconds\nCheck board and work."

        agent = AsyncAgent(
            role="architect",
            workspace=ws,
            board=board,
            executor=executor,
            merge_queue=queue,
            emitter=emitter,
            heartbeat_md=heartbeat_md,
            is_delivery_agent=True,
        )

        async def scenario():
            task = asyncio.create_task(agent.loop())
            # Give the loop ~2s to tick and pull the story
            await asyncio.sleep(2.5)
            agent.stop()
            await asyncio.wait_for(task, timeout=5.0)

        asyncio.run(scenario())
        # Agent pulled S1, transitioned to in_progress, enqueued a merge
        assert board.read("S1").state in ("in_progress", "review", "done")
        assert executor.run_story.called
        assert queue.qsize() >= 1 or board.read("S1").state == "done"

    def test_sleeps_when_no_work(self, tmp_path, real_repo):
        board = BoardStore(tmp_path / "board")  # empty board
        ws = _make_ws(tmp_path, real_repo)
        emitter = EventEmitter(tmp_path)
        queue = MergeQueue(ws)
        executor = MagicMock()
        executor.run_story = MagicMock()

        agent = AsyncAgent(
            role="architect", workspace=ws, board=board,
            executor=executor, merge_queue=queue, emitter=emitter,
            heartbeat_md="## Every 1 seconds\nCheck board.",
            is_delivery_agent=True,
        )

        async def scenario():
            task = asyncio.create_task(agent.loop())
            await asyncio.sleep(1.5)
            agent.stop()
            await asyncio.wait_for(task, timeout=5.0)

        asyncio.run(scenario())
        executor.run_story.assert_not_called()


class TestAsyncAgentCeremonies:
    def test_scrum_master_triggers_retro_by_keyword(self, tmp_path, real_repo, monkeypatch):
        board = BoardStore(tmp_path / "board")
        ws = _make_ws(tmp_path, real_repo)
        ws.team_id = "t1"
        ws.source_repo = real_repo
        ws.manifest = MagicMock(return_value=MagicMock(
            goal="test", model="m", baseline_sha="", created_at="2024-01-01T00:00:00Z"))
        emitter = EventEmitter(tmp_path)
        queue = MergeQueue(ws)
        executor = MagicMock()

        # Intercept retro
        called = {"retro": 0}
        def fake_retro(**kwargs):
            called["retro"] += 1
            return {"went_well": [], "went_wrong": [], "action_item": ""}
        from orgos.agile import retrospective as _retro_mod
        monkeypatch.setattr(_retro_mod, "run_retrospective", fake_retro)

        heartbeat_md = "## Every 1 seconds\nRun the sprint retrospective."

        agent = AsyncAgent(
            role="scrum_master", workspace=ws, board=board,
            executor=executor, merge_queue=queue, emitter=emitter,
            heartbeat_md=heartbeat_md,
            is_delivery_agent=False,
        )

        async def scenario():
            task = asyncio.create_task(agent.loop())
            await asyncio.sleep(1.5)
            agent.stop()
            await asyncio.wait_for(task, timeout=5.0)

        asyncio.run(scenario())
        assert called["retro"] >= 1

    def test_po_replan_text_routes_to_replan_not_retro(self, tmp_path, real_repo, monkeypatch):
        """Regression: PO's HEARTBEAT text mentions RETRO.md but must route to replan."""
        board = BoardStore(tmp_path / "board")
        ws = _make_ws(tmp_path, real_repo)
        ws.team_id = "t1"
        ws.source_repo = real_repo
        ws.manifest = MagicMock(return_value=MagicMock(
            goal="test", model="m", baseline_sha="", created_at="2024-01-01T00:00:00Z"))
        emitter = EventEmitter(tmp_path)
        queue = MergeQueue(ws)
        executor = MagicMock()

        called = {"retro": 0, "replan": 0}
        def fake_retro(**kwargs):
            called["retro"] += 1
            return {"went_well": [], "went_wrong": [], "action_item": ""}
        def fake_replan(**kwargs):
            called["replan"] += 1
            return []
        from orgos.agile import retrospective as _retro_mod
        from orgos.agile import replan as _replan_mod
        monkeypatch.setattr(_retro_mod, "run_retrospective", fake_retro)
        monkeypatch.setattr(_replan_mod, "run_replan", fake_replan)

        # Verbatim text from agents/po/HEARTBEAT.md
        heartbeat_md = (
            "## Every 1 seconds\n"
            "invoke replan(): read the SPEC.md and RETRO.md, draft new stories.\n"
        )
        agent = AsyncAgent(
            role="po", workspace=ws, board=board,
            executor=executor, merge_queue=queue, emitter=emitter,
            heartbeat_md=heartbeat_md,
            is_delivery_agent=False,
        )

        async def scenario():
            task = asyncio.create_task(agent.loop())
            await asyncio.sleep(1.5)
            agent.stop()
            await asyncio.wait_for(task, timeout=5.0)

        asyncio.run(scenario())
        assert called["replan"] >= 1
        assert called["retro"] == 0


class TestAsyncAgentCoordination:
    def test_coordination_agent_skips_board(self, tmp_path, real_repo):
        board = BoardStore(tmp_path / "board")
        board.draft_story(issue_id="S1", title="t", body="b",
                          story_type="architecture")
        board.transition("S1", "refinement", actor="sm")
        board.transition("S1", "ready", actor="sm")

        ws = _make_ws(tmp_path, real_repo)
        emitter = EventEmitter(tmp_path)
        queue = MergeQueue(ws)
        executor = MagicMock()
        executor.run_story = MagicMock()

        # PO is a coordination agent — should NOT pull from board
        agent = AsyncAgent(
            role="po", workspace=ws, board=board,
            executor=executor, merge_queue=queue, emitter=emitter,
            heartbeat_md="## Every 1 seconds\nPlan sprint.",
            is_delivery_agent=False,
        )

        async def scenario():
            task = asyncio.create_task(agent.loop())
            await asyncio.sleep(1.5)
            agent.stop()
            await asyncio.wait_for(task, timeout=5.0)

        asyncio.run(scenario())
        # Should not have touched the board's story
        assert board.read("S1").state == "ready"
        executor.run_story.assert_not_called()

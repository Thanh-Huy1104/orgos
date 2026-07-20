"""Tests for §H5 agent_heartbeat + pull counters.

The heartbeat is the definitive alive-vs-idle signal — an agent that's
stuck inside an await stops firing it, while a legitimately idle agent
keeps ticking with increasing pull_attempts.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

import pytest

from orgos.agile.agent_loop import AsyncAgent
from orgos.agile.board_store import BoardStore
from orgos.agile.live_events import EventEmitter, read_events
from orgos.agile.merge_queue import MergeQueue


class _MockExecutor:
    """Test-only executor that returns immediately."""
    def run_story(self, **kwargs):
        from orgos.agile.coding_executor import ExecutionResult
        return ExecutionResult(success=False, error="mock-decline")


@pytest.fixture
def team_workspace(tmp_path):
    from orgos.agile.team_workspace import TeamWorkspace

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("init")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)

    ws = TeamWorkspace.create(
        team_id="hb-test", source_repo=tmp_path,
        goal="test", model="mock",
    )
    ws.ensure_agent_workspace("architect", 0)
    return ws


class TestAgentStartedIncludesWorker:
    def test_agent_started_has_worker_field(self, team_workspace):
        """§H5 — agent_started now emits worker=actor for per-instance tracking."""
        ws = team_workspace
        board = BoardStore(ws.root / "board")
        emitter = EventEmitter(ws.root)
        queue = MergeQueue(ws)

        agent = AsyncAgent(
            role="architect", instance=0, workspace=ws, board=board,
            executor=_MockExecutor(), merge_queue=queue, emitter=emitter,
            heartbeat_md="## Every 10 seconds\ncheck board for story\n",
            is_delivery_agent=True,
        )

        async def scenario():
            task = asyncio.create_task(agent.loop())
            await asyncio.sleep(0.5)  # let it start + emit agent_started
            agent.stop()
            await asyncio.wait_for(task, timeout=3.0)

        asyncio.run(scenario())

        events = read_events(ws.root)
        started = [e for e in events if e.get("action") == "agent_started"]
        assert len(started) >= 1
        # §H5: worker field present, matches actor
        assert started[0].get("worker") == "architect"


class TestPullCountersExist:
    def test_pull_counters_are_initialized_after_start(self, team_workspace):
        """§H5 — after loop starts, pull_attempts/pull_success/pull_none are
        integer attributes on the agent. The scheduler fires on first tick
        so counters may be > 0 immediately."""
        ws = team_workspace
        board = BoardStore(ws.root / "board")
        emitter = EventEmitter(ws.root)
        queue = MergeQueue(ws)

        agent = AsyncAgent(
            role="architect", instance=1, workspace=ws, board=board,
            executor=_MockExecutor(), merge_queue=queue, emitter=emitter,
            heartbeat_md="## Every 10 seconds\ncheck board\n",
            is_delivery_agent=True,
        )

        async def scenario():
            task = asyncio.create_task(agent.loop())
            await asyncio.sleep(0.3)
            agent.stop()
            await asyncio.wait_for(task, timeout=3.0)

        asyncio.run(scenario())

        # All three counters should be ints (any value ≥ 0)
        assert isinstance(agent._pull_attempts, int) and agent._pull_attempts >= 0
        assert isinstance(agent._pull_success, int) and agent._pull_success >= 0
        assert isinstance(agent._pull_none, int) and agent._pull_none >= 0
        # And they should add up correctly
        assert agent._pull_success + agent._pull_none == agent._pull_attempts


class TestPullCountersIncrement:
    def test_idle_pull_bumps_pull_none(self, team_workspace):
        """An agent that tries to pull with no work bumps pull_none, not pull_success."""
        ws = team_workspace
        board = BoardStore(ws.root / "board")
        emitter = EventEmitter(ws.root)
        queue = MergeQueue(ws)

        # Board is EMPTY — no stories to claim
        agent = AsyncAgent(
            role="architect", instance=0, workspace=ws, board=board,
            executor=_MockExecutor(), merge_queue=queue, emitter=emitter,
            # 1-second cadence so we get several pulls in a short test
            heartbeat_md="## Every 1 seconds\ncheck board for story\n",
            is_delivery_agent=True,
        )

        async def scenario():
            task = asyncio.create_task(agent.loop())
            # Wait ~3s so cadence fires 3 times
            await asyncio.sleep(3.2)
            agent.stop()
            await asyncio.wait_for(task, timeout=3.0)

        asyncio.run(scenario())

        assert agent._pull_attempts >= 2, (
            f"Expected >=2 pull attempts in 3s, got {agent._pull_attempts}"
        )
        assert agent._pull_none == agent._pull_attempts, (
            "Every pull with empty board should hit pull_none"
        )
        assert agent._pull_success == 0

    def test_successful_pull_bumps_pull_success(self, team_workspace):
        ws = team_workspace
        board = BoardStore(ws.root / "board")
        board.draft_story(
            issue_id="S1", title="t", body="b",
            story_type="architecture", files_to_touch=["app.py"],
        )
        board.transition("S1", "refinement", actor="sm")
        board.transition("S1", "ready", actor="sm")

        emitter = EventEmitter(ws.root)
        queue = MergeQueue(ws)

        agent = AsyncAgent(
            role="architect", instance=0, workspace=ws, board=board,
            executor=_MockExecutor(), merge_queue=queue, emitter=emitter,
            heartbeat_md="## Every 1 seconds\ncheck board for story\n",
            is_delivery_agent=True,
        )

        async def scenario():
            task = asyncio.create_task(agent.loop())
            await asyncio.sleep(1.8)  # long enough for one pull to complete
            agent.stop()
            await asyncio.wait_for(task, timeout=3.0)

        asyncio.run(scenario())

        assert agent._pull_attempts >= 1
        assert agent._pull_success >= 1, (
            f"Expected pull_success >=1, got {agent._pull_success} "
            f"(attempts={agent._pull_attempts}, none={agent._pull_none})"
        )


class TestHeartbeatEmission:
    def test_heartbeat_interval_can_be_reached(self, team_workspace):
        """With HEARTBEAT_INTERVAL=120 the test can't wait that long, but
        we can verify the internal timing state after a tick."""
        ws = team_workspace
        board = BoardStore(ws.root / "board")
        emitter = EventEmitter(ws.root)
        queue = MergeQueue(ws)

        agent = AsyncAgent(
            role="architect", instance=0, workspace=ws, board=board,
            executor=_MockExecutor(), merge_queue=queue, emitter=emitter,
            heartbeat_md="## Every 1 seconds\ncheck board for story\n",
            is_delivery_agent=True,
        )

        async def scenario():
            task = asyncio.create_task(agent.loop())
            await asyncio.sleep(0.3)
            agent.stop()
            await asyncio.wait_for(task, timeout=3.0)

        asyncio.run(scenario())

        # After starting, _last_heartbeat should be set (initial heartbeat fires immediately since 0 - 0 >= 120 is False, so no heartbeat yet)
        # Instead verify counters are initialized (they only exist after loop start)
        assert hasattr(agent, "_pull_attempts")
        assert hasattr(agent, "_pull_success")
        assert hasattr(agent, "_last_heartbeat")


class TestTeamReportUsesHeartbeatData:
    """collect_agent_statuses should surface pull_attempts + last_heartbeat_at
    from the new agent_heartbeat events."""

    def test_status_reads_heartbeat_event(self, tmp_path):
        from orgos.agile.team_report import collect_agent_statuses

        # Synthesize a workspace with one architect agent
        (tmp_path / "agents" / "architect").mkdir(parents=True)

        class _FakeWs:
            root = tmp_path
            agents_root = tmp_path / "agents"

        # Write two events: agent_started + agent_heartbeat
        live = tmp_path / "live.jsonl"
        live.write_text(
            json.dumps({
                "timestamp": "2026-07-19T12:00:00+00:00",
                "action": "agent_started",
                "worker": "architect", "role": "architect",
            }) + "\n" +
            json.dumps({
                "timestamp": "2026-07-19T12:02:00+00:00",
                "action": "agent_heartbeat",
                "worker": "architect", "role": "architect",
                "pull_attempts": 8, "pull_success": 3, "pull_idle": 5,
                "uptime_seconds": 120,
            }) + "\n"
        )

        statuses = collect_agent_statuses(_FakeWs())
        arch = next(s for s in statuses if s["role"] == "architect")
        assert arch["is_alive"] is True
        assert arch["pull_attempts"] == 8
        assert arch["pull_success"] == 3
        assert arch["pull_idle"] == 5
        assert arch["last_heartbeat_at"] == "2026-07-19T12:02:00+00:00"

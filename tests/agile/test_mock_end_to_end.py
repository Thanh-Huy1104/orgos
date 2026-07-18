"""End-to-end infrastructure test using MockExecutor.

Wires the full pull → commit → merge → acceptance cycle with 2 mock agents
sharing one merge worker, driving 6 disjoint-component stories. Validates
that the runtime plumbing (board transitions, merge queue serialization,
DoD gate) all agrees at machine speed.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from orgos.agile.agent_loop import AsyncAgent
from orgos.agile.board_store import BoardStore
from orgos.agile.live_events import EventEmitter
from orgos.agile.merge_queue import MergeQueue, run_merge_worker
from orgos.agile.mock_executor import MockExecutor, seed_mock_backlog
from orgos.agile.team_workspace import TeamWorkspace


@pytest.fixture
def real_team(tmp_path):
    """Create a real TeamWorkspace with two architect instances."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("init")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)

    ws = TeamWorkspace.create(
        team_id="e2e-mock", source_repo=tmp_path,
        goal="test", model="mock",
    )
    # Two architect instances
    for i in (0, 1):
        ws.ensure_agent_workspace("architect", i)
    ws.velocity_target = 6
    return ws


class TestFullPullCommitMergeCycle:
    def test_multiple_stories_flow_through_end_to_end(self, real_team):
        ws = real_team
        board = BoardStore(ws.root / "board")
        emitter = EventEmitter(ws.root)
        seed_mock_backlog(board, n_stories=6)

        executor = MockExecutor(wall_seconds=0.01)
        merge_queue = MergeQueue(ws)

        heartbeat = "## Every 1 seconds\nCheck the board and pull stories.\n"
        agents = [
            AsyncAgent(
                role="architect", instance=i, workspace=ws, board=board,
                executor=executor, merge_queue=merge_queue, emitter=emitter,
                heartbeat_md=heartbeat, is_delivery_agent=True,
            )
            for i in (0, 1)
        ]

        async def scenario():
            merge_task = asyncio.create_task(run_merge_worker(
                merge_queue, ws, board, emitter, stop_when_empty=False,
            ))
            agent_tasks = [asyncio.create_task(a.loop()) for a in agents]
            # Let the agents run for a few seconds — long enough to pull &
            # process all 6 stories in parallel with instance ownership.
            await asyncio.sleep(5.0)
            for a in agents:
                a.stop()
            for t in agent_tasks:
                try:
                    await asyncio.wait_for(t, timeout=3.0)
                except asyncio.TimeoutError:
                    t.cancel()
            merge_task.cancel()

        asyncio.run(scenario())

        # At least half the stories should have made it to pending_acceptance
        # or beyond (mock executor commits every story; merge worker turns
        # them into pending_acceptance).
        counts = board.counts_by_state()
        landed = counts.get("pending_acceptance", 0) + counts.get("done", 0)
        assert landed >= 3, (
            f"Expected ≥3 stories to land through the full cycle. "
            f"Actual counts: {counts}"
        )
        # And there should be at least one commit on the integration branch
        # (baseline + agent commits).
        r = subprocess.run(
            ["git", "log", "--oneline"], cwd=ws.integration_worktree,
            capture_output=True, text=True,
        )
        commit_count = len([l for l in r.stdout.splitlines() if l.strip()])
        assert commit_count >= 2, (
            f"Expected merged commits on integration branch. Log: {r.stdout}"
        )

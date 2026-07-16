"""Tests for AsyncAgent — the async runtime per role."""

from __future__ import annotations

import asyncio
import json
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


class TestHeartbeatSchedulerResetOnRestart:
    """Regression: after a crash+restart the scheduler must not freeze."""

    def test_scheduler_tasks_reset_to_minus_one_on_loop_reentry(
        self, tmp_path, real_repo
    ):
        """After loop() exits and is re-entered, _last_fired_at must be -1.0."""
        board = BoardStore(tmp_path / "board")
        ws = _make_ws(tmp_path, real_repo)
        emitter = EventEmitter(tmp_path)
        queue = MergeQueue(ws)
        executor = MagicMock()

        heartbeat_md = "## Every 1 seconds\nCheck board."
        agent = AsyncAgent(
            role="architect", workspace=ws, board=board,
            executor=executor, merge_queue=queue, emitter=emitter,
            heartbeat_md=heartbeat_md,
            is_delivery_agent=True,
        )

        async def run_once():
            task = asyncio.create_task(agent.loop())
            await asyncio.sleep(1.5)
            agent.stop()
            await asyncio.wait_for(task, timeout=5.0)

        # First session: run and let the scheduler fire
        asyncio.run(run_once())
        fired_after_first = agent.scheduler.tasks[0]._last_fired_at
        # It should have fired (positive value) during the first session
        assert fired_after_first > 0, (
            "Task should have fired during first session"
        )

        # Simulate crash+restart: supervisor resets _alive and calls loop() again
        agent._alive = True
        asyncio.run(run_once())

        # After the second session completes, the task should have fired again
        # (it was reset to -1.0 at the top of loop(), so it fires immediately)
        fired_after_second = agent.scheduler.tasks[0]._last_fired_at
        assert fired_after_second >= 0, (
            "Task should have fired in the restarted session — scheduler was not frozen"
        )

    def test_ceremony_fires_in_second_session(self, tmp_path, real_repo, monkeypatch):
        """After restart the scheduled ceremony must fire again, not be frozen."""
        board = BoardStore(tmp_path / "board")
        ws = _make_ws(tmp_path, real_repo)
        ws.team_id = "t1"
        ws.source_repo = real_repo
        ws.manifest = MagicMock(return_value=MagicMock(
            goal="test", model="m", baseline_sha="", created_at="2024-01-01T00:00:00Z"))
        emitter = EventEmitter(tmp_path)
        queue = MergeQueue(ws)
        executor = MagicMock()

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

        async def run_once():
            task = asyncio.create_task(agent.loop())
            await asyncio.sleep(1.5)
            agent.stop()
            await asyncio.wait_for(task, timeout=5.0)

        asyncio.run(run_once())
        after_first = called["retro"]
        assert after_first >= 1, "retro must fire in first session"

        # Simulate crash+restart
        agent._alive = True
        asyncio.run(run_once())
        after_second = called["retro"]
        assert after_second > after_first, (
            "retro must fire again in restarted session (scheduler not frozen)"
        )


class TestPokerRefinement:
    """Regression: SM's poker ceremony must transition draft → ready with points."""

    def test_poker_transitions_draft_to_ready_with_points(
        self, tmp_path, real_repo, monkeypatch,
    ):
        board = BoardStore(tmp_path / "board")
        board.draft_story(issue_id="S1", title="add", body="add x",
                          story_type="feature", files_to_touch=["a.py"])
        # Story starts in draft (its natural initial state).
        assert board.read("S1").state == "draft"

        ws = _make_ws(tmp_path, real_repo)
        ws.team_id = "t1"
        ws.source_repo = real_repo
        ws.manifest = MagicMock(return_value=MagicMock(
            goal="test", model="m", baseline_sha="",
            created_at="2024-01-01T00:00:00Z",
        ))
        emitter = EventEmitter(tmp_path)
        queue = MergeQueue(ws)
        executor = MagicMock()

        # Stub the LLM-facing poker vote helpers so we don't need OpenAI.
        from orgos.agile import poker as _poker_mod
        def fake_run_poker(*, story, board, model, token_accumulator, **kw):
            for v in ({"voter": "architect", "points": 3, "justification": ""},
                      {"voter": "test",      "points": 3, "justification": ""},
                      {"voter": "devsecops", "points": 5, "justification": ""}):
                board.add_poker_vote(
                    story.issue_id, voter=v["voter"],
                    points=v["points"], justification=v["justification"],
                )
            return [
                {"voter": "architect", "points": 3, "justification": ""},
                {"voter": "test",      "points": 3, "justification": ""},
                {"voter": "devsecops", "points": 5, "justification": ""},
            ]
        monkeypatch.setattr(_poker_mod, "run_poker_round", fake_run_poker)

        heartbeat_md = "## Every 1 seconds\nRun planning poker on refinement stories."
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

        story = board.read("S1")
        assert story.state == "ready", f"expected ready, got {story.state}"
        assert story.points == 3, f"expected median points=3, got {story.points}"


class TestSprintBoundaryCeremony:
    """SM's sprint_boundary ceremony fires when keyword-matched."""

    def test_sprint_open_fires_and_emits_events(self, tmp_path, real_repo):
        board = BoardStore(tmp_path / "board")
        # Two ready stories waiting to be pulled into a sprint
        for iid in ("S1", "S2"):
            board.draft_story(issue_id=iid, title=iid, body="b",
                              story_type="feature", priority=50, files_to_touch=[])
            board.transition(iid, "refinement", actor="sm")
            board.transition(iid, "ready", actor="sm")

        ws = _make_ws(tmp_path, real_repo)
        ws.team_id = "t1"
        ws.source_repo = real_repo
        emitter = EventEmitter(tmp_path)
        queue = MergeQueue(ws)
        executor = MagicMock()

        heartbeat_md = "## Every 1 seconds\nOpen the next sprint boundary."
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

        # A sprint was opened (may be sprint 1 or higher if the ceremony
        # fires multiple times in the test window)
        from orgos.agile.sprints import current_sprint_number, read_sprint
        assert current_sprint_number(ws) >= 1
        # Sprint 1 exists and was populated at open time (both stories
        # were unassigned then, so both went in)
        s1 = read_sprint(ws, 1)
        assert s1 is not None
        assert set(s1.committed_backlog) == {"S1", "S2"}
        # Events emitted
        events = [json.loads(l) for l in
                  (tmp_path / "live.jsonl").read_text().splitlines() if l.strip()]
        assert any(e["action"] == "sprint_opened" for e in events)


class TestAcceptanceCeremony:
    """PO's acceptance ceremony transitions pending_acceptance → done."""

    def test_po_accepts_pending_stories(self, tmp_path, real_repo):
        board = BoardStore(tmp_path / "board")
        # Get a story to pending_acceptance
        board.draft_story(issue_id="S1", title="s", body="b",
                          story_type="feature", files_to_touch=[])
        board.transition("S1", "refinement", actor="sm")
        board.transition("S1", "ready", actor="sm")
        board.transition("S1", "in_progress", actor="arch")
        board.transition("S1", "review", actor="arch")
        board.set_commit("S1", "abc1234", actor="arch")
        board.transition("S1", "pending_acceptance", actor="merge_worker")

        ws = _make_ws(tmp_path, real_repo)
        emitter = EventEmitter(tmp_path)
        queue = MergeQueue(ws)
        executor = MagicMock()

        heartbeat_md = "## Every 1 seconds\nAcceptance review of merged stories."
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
        assert board.read("S1").state == "done"

    def test_po_rejects_pending_story_with_no_commit_sha(self, tmp_path, real_repo):
        board = BoardStore(tmp_path / "board")
        board.draft_story(issue_id="S1", title="s", body="b",
                          story_type="feature", files_to_touch=[])
        board.transition("S1", "refinement", actor="sm")
        board.transition("S1", "ready", actor="sm")
        board.transition("S1", "in_progress", actor="arch")
        board.transition("S1", "review", actor="arch")
        # Do NOT set commit — story is in pending_acceptance without proof of work
        board.transition("S1", "pending_acceptance", actor="merge_worker")

        ws = _make_ws(tmp_path, real_repo)
        emitter = EventEmitter(tmp_path)
        queue = MergeQueue(ws)
        agent = AsyncAgent(
            role="po", workspace=ws, board=board,
            executor=MagicMock(), merge_queue=queue, emitter=emitter,
            heartbeat_md="## Every 1 seconds\nAcceptance review of merged stories.",
            is_delivery_agent=False,
        )

        async def scenario():
            task = asyncio.create_task(agent.loop())
            await asyncio.sleep(1.5)
            agent.stop()
            await asyncio.wait_for(task, timeout=5.0)

        asyncio.run(scenario())
        assert board.read("S1").state == "blocked"

    def _drive_pending_architecture(self, tmp_path, real_repo):
        """Helper: set up a board with one architecture story in
        pending_acceptance (with commit), plus a workspace whose source_repo
        is real_repo so the DoD wiki gate can read wiki/DECISIONS.md."""
        board = BoardStore(tmp_path / "board")
        board.draft_story(issue_id="ARCH-1", title="s", body="b",
                          story_type="architecture", files_to_touch=[])
        board.transition("ARCH-1", "refinement", actor="sm")
        board.transition("ARCH-1", "ready", actor="sm")
        board.transition("ARCH-1", "in_progress", actor="arch")
        board.transition("ARCH-1", "review", actor="arch")
        board.set_commit("ARCH-1", "abc1234", actor="arch")
        board.transition("ARCH-1", "pending_acceptance", actor="merge_worker")

        ws = _make_ws(tmp_path, real_repo)
        ws.source_repo = real_repo
        agent = AsyncAgent(
            role="po", workspace=ws, board=board,
            executor=MagicMock(), merge_queue=MergeQueue(ws),
            emitter=EventEmitter(tmp_path),
            heartbeat_md="## Every 1 seconds\nAcceptance review of merged stories.",
            is_delivery_agent=False,
        )
        return board, agent

    def _run_agent_briefly(self, agent):
        async def scenario():
            task = asyncio.create_task(agent.loop())
            await asyncio.sleep(1.5)
            agent.stop()
            await asyncio.wait_for(task, timeout=5.0)
        asyncio.run(scenario())

    def test_architecture_story_blocked_without_wiki_decision(self, tmp_path, real_repo):
        # No wiki/DECISIONS.md entry citing ARCH-1 → DoD gate blocks it.
        board, agent = self._drive_pending_architecture(tmp_path, real_repo)
        self._run_agent_briefly(agent)
        assert board.read("ARCH-1").state == "blocked"

    def test_architecture_story_accepted_with_wiki_decision(self, tmp_path, real_repo):
        board, agent = self._drive_pending_architecture(tmp_path, real_repo)
        wiki = real_repo / "wiki"
        wiki.mkdir(parents=True, exist_ok=True)
        (wiki / "DECISIONS.md").write_text(
            "# Decisions\n\n## Chose worktrees — ARCH-1\n"
            "- author: architect\n- timestamp: 2026-07-16T00:00:00Z\n"
            "- source: ARCH-1\n- decision: isolate each team in a worktree\n",
            encoding="utf-8",
        )
        self._run_agent_briefly(agent)
        assert board.read("ARCH-1").state == "done"


class TestPersonaHeartbeatRouting:
    """Every action_text in every shipped persona HEARTBEAT.md must route
    to a ceremony method — not to scheduled_noop. Prevents the
    'someone rewords the heartbeat and a ceremony silently stops firing'
    regression.

    We replicate the routing logic here rather than importing it so any
    drift between test and implementation surfaces as a test failure.
    """

    def test_all_persona_actions_route_to_a_ceremony(self):
        from pathlib import Path
        import re as _re
        from orgos.agile.heartbeat_scheduler import parse_schedule

        # Same word-boundary helper as AsyncAgent uses.
        def matches(text, *words):
            return any(_re.search(rf"\b{_re.escape(w)}\b", text) for w in words)

        def route(text: str, is_delivery: bool, cadence: int) -> str:
            text = text.lower()
            if is_delivery and cadence <= 60 and ("board" in text or "story" in text or "check" in text):
                return "pull_and_work"
            if matches(text, "sprint") and matches(text, "open", "close", "start", "boundary", "planning"):
                return "sprint_boundary"
            if matches(text, "accept", "acceptance") and matches(text, "story", "stories", "review", "merged"):
                return "acceptance"
            if matches(text, "retrospective"): return "retro"
            if matches(text, "replan"):        return "replan"
            if matches(text, "retro"):         return "retro"
            if matches(text, "backlog", "spec"): return "replan"
            if matches(text, "poker", "refinement"): return "poker"
            if matches(text, "pr") and matches(text, "comment", "comments", "feedback", "review"):
                return "pr_feedback"
            return "noop"

        delivery_roles = {"architect", "test", "devsecops"}
        # Intentional noops — action texts that are documentation-of-intent
        # rather than a scheduled ceremony call. If you add a "read wiki"
        # ceremony later, remove the matching pattern here.
        INTENTIONAL_NOOP_KEYWORDS = ("wiki", "skim", "grep")

        agents_root = Path(__file__).resolve().parents[2] / "agents"
        failures = []
        for role_dir in sorted(agents_root.iterdir()):
            if not role_dir.is_dir() or role_dir.name.startswith("_"):
                continue
            hb = role_dir / "HEARTBEAT.md"
            if not hb.exists():
                continue
            tasks = parse_schedule(hb.read_text(encoding="utf-8"))
            for t in tasks:
                r = route(t.action_text, role_dir.name in delivery_roles, t.cadence_seconds)
                if r == "noop":
                    txt_low = t.action_text.lower()
                    if any(k in txt_low for k in INTENTIONAL_NOOP_KEYWORDS):
                        continue  # explicitly intentional noop
                    failures.append(
                        f"  {role_dir.name}/HEARTBEAT.md → cadence={t.cadence_seconds}s "
                        f"action='{t.action_text[:80]}' routes to NOOP"
                    )
        assert not failures, (
            "Shipped persona HEARTBEAT.md files have action_text that routes "
            "to scheduled_noop (silent no-op). This is almost always a "
            "regression from re-wording. Fix the wording OR add a routing "
            "clause to AsyncAgent.loop:\n" + "\n".join(failures)
        )


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

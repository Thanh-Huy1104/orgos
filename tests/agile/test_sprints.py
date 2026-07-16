"""Tests for the sprint model — sprint boundaries + planning."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from orgos.agile.board_store import BoardStore
from orgos.agile.sprints import (
    Sprint, close_sprint, current_sprint_number, open_sprint, read_sprint,
)


def _fake_workspace(root: Path) -> MagicMock:
    ws = MagicMock()
    ws.root = root
    return ws


class TestSprintLifecycle:
    def test_no_sprints_initially(self, tmp_path):
        ws = _fake_workspace(tmp_path)
        assert current_sprint_number(ws) == 0
        assert read_sprint(ws, 1) is None

    def test_open_sprint_selects_ready_stories(self, tmp_path):
        board = BoardStore(tmp_path / "board")
        ws = _fake_workspace(tmp_path)
        # Draft 3 ready stories with different priorities
        for iid, prio in [("S1", 90), ("S2", 50), ("S3", 30)]:
            board.draft_story(issue_id=iid, title=iid, body="b",
                              story_type="feature", priority=prio,
                              files_to_touch=[])
            board.transition(iid, "refinement", actor="sm")
            board.transition(iid, "ready", actor="sm")

        sprint = open_sprint(ws, board, velocity_target=2)
        assert sprint.number == 1
        assert current_sprint_number(ws) == 1
        # Higher priority picked first
        assert set(sprint.committed_backlog) == {"S1", "S2"}
        assert board.read("S1").sprint_number == 1
        assert board.read("S2").sprint_number == 1
        assert board.read("S3").sprint_number == 0  # not picked

    def test_close_sprint_populates_metrics(self, tmp_path):
        board = BoardStore(tmp_path / "board")
        ws = _fake_workspace(tmp_path)
        for iid in ("S1", "S2"):
            board.draft_story(issue_id=iid, title=iid, body="b",
                              story_type="feature", priority=50, files_to_touch=[])
            board.transition(iid, "refinement", actor="sm")
            board.transition(iid, "ready", actor="sm")
        open_sprint(ws, board, velocity_target=2)
        # Set points + walk S1 through to done
        board.set_points("S1", 5, actor="sm")
        board.set_points("S2", 3, actor="sm")
        board.transition("S1", "in_progress", actor="arch")
        board.transition("S1", "review", actor="arch")
        board.transition("S1", "pending_acceptance", actor="merge_worker")
        board.transition("S1", "done", actor="po", reason="accepted")

        closed = close_sprint(ws, board, reason="scheduled")
        assert closed is not None
        assert closed.ended_at != ""
        assert closed.stories_done == ["S1"]
        assert closed.points_completed == 5  # only S1 done, S2 still in ready

    def test_open_next_sprint_after_close(self, tmp_path):
        board = BoardStore(tmp_path / "board")
        ws = _fake_workspace(tmp_path)
        # Two stories; put both in sprint 1
        for iid in ("S1", "S2"):
            board.draft_story(issue_id=iid, title=iid, body="b",
                              story_type="feature", priority=50, files_to_touch=[])
            board.transition(iid, "refinement", actor="sm")
            board.transition(iid, "ready", actor="sm")
        s1 = open_sprint(ws, board, velocity_target=2)
        assert s1.number == 1
        # Add a NEW story to the backlog (will be pulled into sprint 2)
        board.draft_story(issue_id="S3", title="S3", body="b",
                          story_type="feature", priority=50, files_to_touch=[])
        board.transition("S3", "refinement", actor="sm")
        board.transition("S3", "ready", actor="sm")

        s2 = open_sprint(ws, board, velocity_target=2)
        assert s2.number == 2
        assert current_sprint_number(ws) == 2
        # S3 should be in sprint 2; S1/S2 should still be in sprint 1
        assert board.read("S3").sprint_number == 2
        assert board.read("S1").sprint_number == 1
        assert board.read("S2").sprint_number == 1
        # Sprint 1 should have been auto-closed by the second open_sprint
        s1_reread = read_sprint(ws, 1)
        assert s1_reread.ended_at != ""

    def test_sprint_filter_hides_other_sprints_from_pull(self, tmp_path):
        board = BoardStore(tmp_path / "board")
        ws = _fake_workspace(tmp_path)
        for iid in ("S1", "S2"):
            board.draft_story(issue_id=iid, title=iid, body="b",
                              story_type="feature", priority=50, files_to_touch=[])
            board.transition(iid, "refinement", actor="sm")
            board.transition(iid, "ready", actor="sm")
        open_sprint(ws, board, velocity_target=1)   # only S1 committed
        # Pull with sprint_number=1 → only S1 is claimable
        s = board.try_claim_next_for("architect", actor="arch1", sprint_number=1)
        assert s is not None
        assert s.issue_id == "S1"
        # Second pull should return None (S2 is in sprint 0, not sprint 1)
        s2 = board.try_claim_next_for("architect", actor="arch2", sprint_number=1)
        assert s2 is None


class TestSprintFilterBackwardCompat:
    def test_sprint_zero_returns_all(self, tmp_path):
        """With no sprints opened yet, pulls should behave like before."""
        board = BoardStore(tmp_path / "board")
        board.draft_story(issue_id="S1", title="s", body="b",
                          story_type="architecture", files_to_touch=[])
        board.transition("S1", "refinement", actor="sm")
        board.transition("S1", "ready", actor="sm")
        s = board.try_claim_next_for("architect", actor="a", sprint_number=0)
        assert s is not None
        assert s.issue_id == "S1"

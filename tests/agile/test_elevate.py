"""Tests for auto-priority elevation (Fix §B7)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from orgos.agile.board_store import BoardStore
from orgos.agile.elevate import (
    ElevationConfig, run_elevation_pass, _seconds_since, _bump_count,
)


def _at(iso: str):
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


class TestParsing:
    def test_seconds_since(self):
        now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        assert _seconds_since("2026-01-01T11:00:00+00:00", now) == 3600
        assert _seconds_since("", now) is None
        assert _seconds_since("not-a-date", now) is None


class TestReadyElevation:
    def test_fresh_story_not_elevated(self, tmp_path):
        board = BoardStore(tmp_path / "board")
        board.draft_story(
            issue_id="S1", title="fresh", body="", story_type="feature",
            files_to_touch=["a.py"], priority=50,
        )
        board.transition("S1", "refinement", actor="sm")
        board.transition("S1", "ready", actor="sm")
        # simulate "now" = 5 min later (below 30-min threshold)
        cfg = ElevationConfig(
            now_fn=lambda: datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        emitter = MagicMock()
        counts = run_elevation_pass(board, emitter, cfg)
        assert counts["elevated_ready"] == 0
        assert board.read("S1").priority == 50

    def test_stale_story_gets_bumped(self, tmp_path):
        board = BoardStore(tmp_path / "board")
        board.draft_story(
            issue_id="S1", title="old", body="", story_type="feature",
            files_to_touch=["a.py"], priority=50,
        )
        board.transition("S1", "refinement", actor="sm")
        board.transition("S1", "ready", actor="sm")
        # now = 45 min later (over 30-min threshold)
        cfg = ElevationConfig(
            now_fn=lambda: datetime.now(timezone.utc) + timedelta(minutes=45),
        )
        emitter = MagicMock()
        counts = run_elevation_pass(board, emitter, cfg)
        assert counts["elevated_ready"] == 1
        assert board.read("S1").priority == 65
        # An audit entry should have been added
        trail = board.audit_trail("S1")
        assert any(e["action"] == "elevate_priority" for e in trail)

    def test_max_bumps_cap(self, tmp_path):
        board = BoardStore(tmp_path / "board")
        board.draft_story(
            issue_id="S1", title="stuck", body="", story_type="feature",
            files_to_touch=["a.py"], priority=50,
        )
        board.transition("S1", "refinement", actor="sm")
        board.transition("S1", "ready", actor="sm")
        # Bump 3 times, then verify 4th call skips
        cfg = ElevationConfig(
            now_fn=lambda: datetime.now(timezone.utc) + timedelta(hours=10),
            max_bumps_per_story=3,
        )
        emitter = MagicMock()
        for _ in range(3):
            run_elevation_pass(board, emitter, cfg)
        # Now try a 4th pass — should skip
        counts = run_elevation_pass(board, emitter, cfg)
        assert counts["elevated_ready"] == 0
        assert counts["skipped_max_bumps"] == 1
        assert _bump_count(board, "S1") == 3


class TestInProgressReclaim:
    def test_fresh_in_progress_not_reclaimed(self, tmp_path):
        board = BoardStore(tmp_path / "board")
        board.draft_story(
            issue_id="S1", title="live", body="", story_type="feature",
            files_to_touch=["a.py"], priority=50,
        )
        board.transition("S1", "refinement", actor="sm")
        board.transition("S1", "ready", actor="sm")
        board.assign("S1", "arch")
        board.transition("S1", "in_progress", actor="arch")
        cfg = ElevationConfig(
            now_fn=lambda: datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        emitter = MagicMock()
        counts = run_elevation_pass(board, emitter, cfg)
        assert counts["reclaimed_in_progress"] == 0
        assert board.read("S1").state == "in_progress"

    def test_stuck_in_progress_gets_reclaimed(self, tmp_path):
        board = BoardStore(tmp_path / "board")
        board.draft_story(
            issue_id="S1", title="stuck", body="", story_type="feature",
            files_to_touch=["a.py"], priority=50,
        )
        board.transition("S1", "refinement", actor="sm")
        board.transition("S1", "ready", actor="sm")
        board.assign("S1", "arch")
        board.transition("S1", "in_progress", actor="arch")
        # now = 20 min later, above 15-min threshold
        cfg = ElevationConfig(
            now_fn=lambda: datetime.now(timezone.utc) + timedelta(minutes=20),
        )
        emitter = MagicMock()
        counts = run_elevation_pass(board, emitter, cfg)
        assert counts["reclaimed_in_progress"] == 1
        fresh = board.read("S1")
        assert fresh.state == "ready"
        assert fresh.priority == 65  # bumped +15
        assert fresh.attempts >= 1

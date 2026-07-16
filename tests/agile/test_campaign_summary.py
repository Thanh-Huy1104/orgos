"""Tests for scrum's campaign_result.json shutdown aggregator."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from orgos.agile.board_store import BoardStore
from orgos.agile.campaign_summary import write_campaign_result
from orgos.agile.live_events import EventEmitter


def _fake_workspace(root: Path) -> MagicMock:
    ws = MagicMock()
    ws.root = root
    ws.manifest = MagicMock(return_value=SimpleNamespace(
        team_id="t1", goal="add x", model="deepseek/deepseek-chat",
    ))
    return ws


class TestWriteCampaignResult:
    def test_sums_tokens_and_wall_across_events(self, tmp_path):
        board = BoardStore(tmp_path / "board")
        ws = _fake_workspace(tmp_path)
        emitter = EventEmitter(tmp_path)

        # Simulate a scrum session: 2 commits + 1 failed attempt
        emitter.emit("commit_landed", story_id="S1", commit_sha="aaa",
                     worker="architect", tokens_in=100, tokens_out=50,
                     wall_seconds=12.5, summary="")
        emitter.emit("commit_landed", story_id="S2", commit_sha="bbb",
                     worker="test", tokens_in=200, tokens_out=80,
                     wall_seconds=8.0, summary="")
        emitter.emit("story_no_commit", story_id="S3", worker="architect",
                     tokens_in=150, tokens_out=30, wall_seconds=15.0,
                     summary="executor timeout")

        # Board reflects real state
        for iid in ("S1", "S2", "S3"):
            board.draft_story(issue_id=iid, title=iid, body="b",
                              story_type="feature", files_to_touch=[])
            board.transition(iid, "refinement", actor="sm")
            board.transition(iid, "ready", actor="sm")
        board.transition("S1", "in_progress", actor="arch")
        board.transition("S1", "review", actor="arch")
        board.transition("S1", "done", actor="merge_worker")
        board.transition("S2", "in_progress", actor="test")
        board.transition("S2", "review", actor="test")
        board.transition("S2", "done", actor="merge_worker")
        board.transition("S3", "in_progress", actor="arch")
        board.transition("S3", "blocked", actor="arch",
                         reason="executor timeout")

        out = write_campaign_result(
            ws, board, executor="spawn", reason_stopped="timeout",
        )
        assert out.exists()
        data = json.loads(out.read_text())

        # Aggregate totals
        assert data["total_tokens_input"] == 450   # 100 + 200 + 150
        assert data["total_tokens_output"] == 160  # 50 + 80 + 30
        assert data["stories_created"] == 3
        assert data["stories_done"] == 2
        assert data["stories_blocked"] == 1

        # Per-story record shape
        by_id = {r["story_id"]: r for r in data["per_story_results"]}
        assert by_id["S1"]["commit_sha"] == "aaa"
        assert by_id["S1"]["status"] == "committed"
        assert by_id["S1"]["tokens_in"] == 100
        assert by_id["S1"]["worker"] == "architect"
        assert by_id["S3"]["status"] == "no_commit"
        assert by_id["S3"]["tokens_in"] == 150

        # Metadata
        assert data["team_id"] == "t1"
        assert data["executor"] == "spawn"
        assert data["topology"] == "scrum"
        assert data["reason_stopped"] == "timeout"

    def test_empty_events_still_writes_valid_file(self, tmp_path):
        board = BoardStore(tmp_path / "board")
        ws = _fake_workspace(tmp_path)
        out = write_campaign_result(
            ws, board, executor="claude", reason_stopped="sigint",
        )
        data = json.loads(out.read_text())
        assert data["stories_created"] == 0
        assert data["total_tokens_input"] == 0
        assert data["per_story_results"] == []

    def test_multiple_commits_for_same_story_sum(self, tmp_path):
        """If an agent retries a story (rare but possible), tokens should sum."""
        board = BoardStore(tmp_path / "board")
        ws = _fake_workspace(tmp_path)
        emitter = EventEmitter(tmp_path)
        emitter.emit("story_no_commit", story_id="S1", worker="architect",
                     tokens_in=100, tokens_out=50, wall_seconds=10.0,
                     summary="first attempt failed")
        emitter.emit("commit_landed", story_id="S1", commit_sha="aaa",
                     worker="architect", tokens_in=80, tokens_out=40,
                     wall_seconds=6.0, summary="second attempt")
        board.draft_story(issue_id="S1", title="t", body="b",
                          story_type="feature", files_to_touch=[])
        board.transition("S1", "refinement", actor="sm")
        board.transition("S1", "ready", actor="sm")
        board.transition("S1", "in_progress", actor="arch")
        board.transition("S1", "review", actor="arch")
        board.transition("S1", "done", actor="merge_worker")

        out = write_campaign_result(
            ws, board, executor="spawn", reason_stopped="timeout",
        )
        data = json.loads(out.read_text())
        rec = data["per_story_results"][0]
        assert rec["tokens_in"] == 180   # 100 + 80
        assert rec["tokens_out"] == 90   # 50 + 40
        assert rec["status"] == "committed"  # final state wins

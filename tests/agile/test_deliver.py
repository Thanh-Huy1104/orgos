"""Tests for orgos deliver — spec-vs-delivered reconciliation (Fix §A3)."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock

import pytest

from orgos.agile.board_store import BoardStore
from orgos.agile.deliver import (
    _match_declared_to_board, _normalize_title,
    build_report, format_receipt,
)


class TestNormalizeTitle:
    def test_lowercases(self):
        assert _normalize_title("Add /health Endpoint") == "add health endpoint"

    def test_strips_punctuation(self):
        assert _normalize_title("Fix bug! (finally)") == "fix bug finally"

    def test_empty_input(self):
        assert _normalize_title("") == ""
        assert _normalize_title(None) == ""


class TestMatching:
    def test_exact_normalized_match(self, tmp_path):
        board = BoardStore(tmp_path / "board")
        board.draft_story(
            issue_id="S1", title="Add /health endpoint", body="",
            story_type="feature", files_to_touch=["app.py"],
        )
        declared = [MagicMock(title="Add /health endpoint",
                              acceptance_criteria=[])]
        rows = _match_declared_to_board(declared, board.all_stories())
        assert rows[0].matched_story_id == "S1"

    def test_substring_fallback(self, tmp_path):
        board = BoardStore(tmp_path / "board")
        board.draft_story(
            issue_id="S1", title="Add /health endpoint returning JSON", body="",
            story_type="feature", files_to_touch=["app.py"],
        )
        declared = [MagicMock(title="Add /health endpoint",
                              acceptance_criteria=[])]
        rows = _match_declared_to_board(declared, board.all_stories())
        assert rows[0].matched_story_id == "S1"

    def test_no_double_claim(self, tmp_path):
        # Two declared stories can't both claim the same board story
        board = BoardStore(tmp_path / "board")
        board.draft_story(
            issue_id="S1", title="Health endpoint work", body="",
            story_type="feature", files_to_touch=["app.py"],
        )
        declared = [
            MagicMock(title="Health endpoint", acceptance_criteria=[]),
            MagicMock(title="Health endpoint", acceptance_criteria=[]),
        ]
        rows = _match_declared_to_board(declared, board.all_stories())
        assert rows[0].matched_story_id == "S1"
        assert rows[1].matched_story_id is None

    def test_no_match_when_disjoint(self, tmp_path):
        board = BoardStore(tmp_path / "board")
        board.draft_story(
            issue_id="S1", title="Refactor auth", body="",
            story_type="architecture", files_to_touch=["auth.py"],
        )
        declared = [MagicMock(title="Add payments", acceptance_criteria=[])]
        rows = _match_declared_to_board(declared, board.all_stories())
        assert rows[0].matched_story_id is None
        assert rows[0].state == "not_matched"


@pytest.fixture
def workspace_with_stories(tmp_path):
    """Real TeamWorkspace with a few stories in various states."""
    from orgos.agile.team_workspace import TeamWorkspace

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("init")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)

    ws = TeamWorkspace.create(
        team_id="deliver-test", source_repo=tmp_path,
        goal="test", model="deepseek/deepseek-chat",
    )
    board = BoardStore(ws.root / "board")

    # 3 stories: one done, one blocked, one still in draft
    for i, (title, files, state) in enumerate([
        ("Set up scaffolding", ["pyproject.toml"], "done"),
        ("Add /health endpoint", ["app.py"], "blocked"),
        ("Add tests for health", ["tests/test_health.py"], "draft"),
    ]):
        board.draft_story(
            issue_id=f"S{i}", title=title, body="",
            story_type="feature", files_to_touch=files,
            acceptance_criteria=[f"AC-{i}-a", f"AC-{i}-b"],
        )
        # Walk states as needed
        if state != "draft":
            board.transition(f"S{i}", "refinement", actor="sm")
            board.transition(f"S{i}", "ready", actor="sm")
            board.transition(f"S{i}", "in_progress", actor="arch")
            board.transition(f"S{i}", "review", actor="arch")
            board.set_commit(f"S{i}", "abc" + str(i) * 3, actor="arch")
            if state == "done":
                board.transition(f"S{i}", "pending_acceptance", actor="merge")
                board.transition(f"S{i}", "done", actor="po")
            elif state == "blocked":
                board.transition(f"S{i}", "blocked", actor="po",
                                  reason="merge_conflict: rebase failed")
    return ws, board


class TestBuildReport:
    def test_full_report_shape(self, workspace_with_stories):
        ws, board = workspace_with_stories
        spec = """# spec
## Story: Set up scaffolding
Files: pyproject.toml

## Story: Add /health endpoint
Files: app.py

## Story: Add tests for health
Files: tests/test_health.py

## Story: A story never drafted
Files: nowhere.py
"""
        report = build_report(
            workspace=ws, board=board, spec_text=spec,
            spec_path=ws.root / "SPEC.md",
        )
        assert report.declared_count == 4
        assert report.delivered_count == 1  # only S0 is done
        assert report.blocked_count == 1
        assert report.not_matched_count == 1
        assert report.team_id == "deliver-test"

    def test_receipt_markdown_has_key_sections(self, workspace_with_stories):
        ws, board = workspace_with_stories
        spec = "## Story: Set up scaffolding\nFiles: pyproject.toml\n"
        report = build_report(
            workspace=ws, board=board, spec_text=spec,
            spec_path=ws.root / "SPEC.md",
        )
        md = format_receipt(report)
        assert "delivery receipt" in md.lower()
        assert "Delivered" in md
        assert "Verdict" in md
        assert "deliver-test" in md

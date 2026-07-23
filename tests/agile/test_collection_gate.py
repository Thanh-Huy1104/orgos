"""Tests for §H9 post-merge collection check."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from orgos.agile.board_store import BoardStore
from orgos.agile.collection_gate import (
    check_collection, apply_collection_gate,
)


def _make_workspace(tmp_path):
    """A minimal workspace mock with integration_worktree."""
    ws = MagicMock()
    ws.integration_worktree = tmp_path
    return ws


def _init_repo_with_pyproject(tmp_path):
    """Create a repo with pyproject.toml so pytest can find the package."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "0.1.0"\n'
    )
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "__init__.py").write_text("")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "__init__.py").write_text("")


class TestCheckCollection:
    def test_good_repo_returns_ok(self, tmp_path):
        _init_repo_with_pyproject(tmp_path)
        (tmp_path / "tests" / "test_smoke.py").write_text(
            "def test_one():\n    assert True\n"
        )
        ok, broken, _ = check_collection(tmp_path, timeout=15)
        assert ok is True
        assert broken == []

    def test_no_tests_still_returns_ok(self, tmp_path):
        _init_repo_with_pyproject(tmp_path)
        # No test files at all — pytest exits 5 "no tests collected", treat as OK
        ok, broken, _ = check_collection(tmp_path, timeout=15)
        assert ok is True

    def test_syntax_error_detected(self, tmp_path):
        _init_repo_with_pyproject(tmp_path)
        (tmp_path / "tests" / "test_broken.py").write_text(
            "def test_x():\n    x = [1, 2, 3\n"  # unclosed bracket
        )
        (tmp_path / "tests" / "test_good.py").write_text(
            "def test_y():\n    assert True\n"
        )
        ok, broken, tail = check_collection(tmp_path, timeout=15)
        assert ok is False
        assert any("test_broken.py" in b for b in broken)
        assert tail  # non-empty diagnostic

    def test_missing_worktree_returns_ok(self, tmp_path):
        """§H9 fail-open: no worktree → return OK, don't block work."""
        # pytest can't run in a non-existent dir; subprocess errors, we catch it
        ok, broken, _ = check_collection(
            tmp_path / "does-not-exist", timeout=5,
        )
        assert ok is True  # fail-open


class TestApplyCollectionGate:
    def _draft_pending_story(self, board, issue_id):
        board.draft_story(
            issue_id=issue_id, title="t", body="body",
            story_type="test", files_to_touch=["tests/test_x.py"],
            acceptance_criteria=["it works"],
        )
        board.transition(issue_id, "refinement", actor="sm")
        board.transition(issue_id, "ready", actor="sm")
        board.transition(issue_id, "in_progress", actor="arch")
        board.transition(issue_id, "review", actor="arch")
        board.set_commit(issue_id, "abc123", actor="arch")
        board.transition(issue_id, "pending_acceptance", actor="merge")

    def test_clean_collection_leaves_story_alone(self, tmp_path):
        _init_repo_with_pyproject(tmp_path)
        (tmp_path / "tests" / "test_smoke.py").write_text(
            "def test_ok():\n    assert True\n"
        )
        board = BoardStore(tmp_path / "board")
        self._draft_pending_story(board, "S1")
        ws = _make_workspace(tmp_path)
        emitter = MagicMock()

        ok = apply_collection_gate(ws, board, "S1", emitter, timeout=15)
        assert ok is True
        assert board.read("S1").state == "pending_acceptance"  # unchanged

    def test_broken_collection_sends_story_back_to_ready(self, tmp_path):
        _init_repo_with_pyproject(tmp_path)
        (tmp_path / "tests" / "test_bad.py").write_text(
            "def test_x():\n    x = [1, 2, 3\n"
        )
        board = BoardStore(tmp_path / "board")
        self._draft_pending_story(board, "S1")
        ws = _make_workspace(tmp_path)
        emitter = MagicMock()

        ok = apply_collection_gate(ws, board, "S1", emitter, timeout=15)
        assert ok is False

        story = board.read("S1")
        assert story.state == "ready"
        assert story.commit_sha == ""  # cleared for re-attempt
        # Feedback injected into body
        assert "PREVIOUS ATTEMPT BROKE THE INTEGRATION BRANCH" in story.body
        assert "test_bad.py" in story.body

        # Event emitted
        actions_emitted = [c.args[0] for c in emitter.emit.call_args_list]
        assert "integration_collection_broken" in actions_emitted
        assert "story_reopened_collection" in actions_emitted

    def test_gate_failopen_on_gate_exception(self, tmp_path):
        """If our gate itself throws (bug in check_collection), return True
        so merges keep flowing rather than deadlocking the queue."""
        board = BoardStore(tmp_path / "board")
        self._draft_pending_story(board, "S1")
        ws = MagicMock()
        # Boom: getattr integration_worktree raises
        type(ws).integration_worktree = property(
            lambda s: (_ for _ in ()).throw(RuntimeError("boom"))
        )
        emitter = MagicMock()
        ok = apply_collection_gate(ws, board, "S1", emitter, timeout=5)
        assert ok is True

    def test_story_not_in_pending_acceptance_no_transition(self, tmp_path):
        """If the story has already moved past pending_acceptance (PO accepted
        it faster than the gate ran), we log the event but don't force a
        transition."""
        _init_repo_with_pyproject(tmp_path)
        (tmp_path / "tests" / "test_bad.py").write_text(
            "def test_x():\n    x = [1, 2, 3\n"
        )
        board = BoardStore(tmp_path / "board")
        self._draft_pending_story(board, "S1")
        # PO accepted before us
        board.transition("S1", "done", actor="po")
        ws = _make_workspace(tmp_path)
        emitter = MagicMock()

        ok = apply_collection_gate(ws, board, "S1", emitter, timeout=15)
        assert ok is False  # gate says broken
        # But story stays done — we don't force it back once PO has ruled
        assert board.read("S1").state == "done"
        # Event still emitted for the record
        actions = [c.args[0] for c in emitter.emit.call_args_list]
        assert "integration_collection_broken" in actions

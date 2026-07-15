"""Tests for the quality rubric + evaluator."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from orgos.agile.quality_rubric import (
    check_diff_size,
    check_files_in_scope,
    check_secrets,
    check_commit_valid,
    check_tests_passed,
    evaluate,
)


class TestDiffSize:
    def test_small_diff_passes(self):
        ok, reason = check_diff_size("+line1\n-line2")
        assert ok

    def test_large_diff_fails(self):
        lines = "\n".join([f"+line {i}" for i in range(500)])
        ok, reason = check_diff_size(lines)
        assert not ok

    def test_ignores_header_lines(self):
        lines = "+++ b/file.py\n--- a/file.py\n" + "\n".join([f"+line {i}" for i in range(10)])
        ok, _ = check_diff_size(lines)
        assert ok


class TestFilesInScope:
    def test_all_in_scope(self):
        ok, _ = check_files_in_scope(["orgos/agile/flow_metric.py"], ["orgos/agile/flow_metric.py"])
        assert ok

    def test_outside_scope(self):
        ok, reason = check_files_in_scope(["orgos/api.py"], ["orgos/agile/flow_metric.py"])
        assert not ok
        assert "outside scope" in reason

    def test_no_allowlist_accepts_all(self):
        ok, _ = check_files_in_scope(["anything.py"], None)
        assert ok


class TestSecrets:
    def test_no_secrets(self):
        ok, _ = check_secrets("+def foo():\n+    return 42")
        assert ok

    def test_detects_api_key(self):
        ok, reason = check_secrets('+DEEPSEEK_API_KEY=sk-abc123def456ghi789jkl012mno345pqr678stu')
        assert not ok
        assert "secret" in reason

    def test_detects_password_assignment(self):
        ok, reason = check_secrets('+password = "hunter2"')
        assert not ok


class TestTestsPassed:
    def test_passed(self):
        ok, _ = check_tests_passed("All tests passed! exit code: 0")
        assert ok

    def test_failed(self):
        ok, _ = check_tests_passed("FAILED: 3 tests failed")
        assert not ok


class TestEvaluate:
    def test_evaluate_on_real_worktree(self, tmp_path: Path):
        # Create a git repo with a commit, then make working tree change
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "config", "user.name", "test"], cwd=tmp_path, capture_output=True)

        (tmp_path / "file.py").write_text("old content")
        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=tmp_path, capture_output=True)

        (tmp_path / "file.py").write_text("new content")

        result = evaluate(tmp_path, test_output="All tests passed!")
        assert "score" in result
        assert "criteria" in result
        # With unstaged change only, diff_size should see the change
        assert result["criteria"]["diff_size"]["passed"]

    def test_evaluate_missing_worktree_is_handled(self):
        result = evaluate(Path("/nonexistent"))
        assert result["score"] == 0.0
        assert all(not c["passed"] for c in result["criteria"].values())

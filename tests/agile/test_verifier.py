"""Tests for the overall DoD verifier (Fix §C10)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from orgos.agile.verifier import (
    VerificationResult, _parse_pytest_output, _repo_looks_installable,
    verify_integration,
)


class TestParseOutput:
    def test_all_passed(self):
        out = "..........  [100%]\n\n10 passed in 0.42s"
        counts = _parse_pytest_output(out)
        assert counts["passed"] == 10
        assert counts["failed"] == 0
        assert counts["duration_seconds"] == 0.42

    def test_mixed(self):
        out = "..F.E.  [100%]\n\n4 passed, 1 failed, 1 error in 1.20s"
        counts = _parse_pytest_output(out)
        assert counts["passed"] == 4
        assert counts["failed"] == 1
        assert counts["errors"] == 1
        assert counts["duration_seconds"] == 1.20

    def test_with_warnings_ignored(self):
        out = "..  [100%]\n\n2 passed, 3 warnings in 0.10s"
        counts = _parse_pytest_output(out)
        assert counts["passed"] == 2
        assert counts["failed"] == 0

    def test_no_tests(self):
        out = "no tests ran in 0.00s"
        counts = _parse_pytest_output(out)
        assert counts["passed"] == 0
        assert counts["failed"] == 0


class TestInstallability:
    def test_looks_installable_with_pyproject(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text('[project]\nname="x"\nversion="0.1"\n')
        assert _repo_looks_installable(tmp_path) is True

    def test_not_installable_bare(self, tmp_path):
        assert _repo_looks_installable(tmp_path) is False


@pytest.fixture
def worktree_with_passing_tests(tmp_path):
    """Bare directory with a trivial pytest suite that passes."""
    (tmp_path / "test_smoke.py").write_text(
        "def test_one():\n    assert 1 + 1 == 2\n"
        "def test_two():\n    assert 'x' == 'x'\n"
    )
    return tmp_path


@pytest.fixture
def worktree_with_failing_test(tmp_path):
    (tmp_path / "test_broken.py").write_text(
        "def test_ok():\n    assert True\n"
        "def test_bad():\n    assert False\n"
    )
    return tmp_path


class TestVerifyIntegration:
    def test_reuse_current_python_all_passing(self, worktree_with_passing_tests):
        result = verify_integration(
            integration_worktree=worktree_with_passing_tests,
            reuse_current_python=True,
        )
        assert result.verified is True
        assert result.passed == 2
        assert result.failed == 0
        assert result.pass_rate == 1.0

    def test_reuse_current_python_with_failure(self, worktree_with_failing_test):
        result = verify_integration(
            integration_worktree=worktree_with_failing_test,
            reuse_current_python=True,
        )
        assert result.verified is True
        assert result.passed == 1
        assert result.failed == 1
        assert result.pass_rate == 0.5

    def test_missing_worktree(self):
        result = verify_integration(
            integration_worktree=Path("/no/such/path"),
            reuse_current_python=True,
        )
        assert result.verified is False
        assert "not found" in result.reason_not_verified

    def test_not_installable_returns_not_verified(self, tmp_path):
        # No pyproject/setup, and using production path
        result = verify_integration(
            integration_worktree=tmp_path,
            use_venv=False,
            reuse_current_python=False,
        )
        assert result.verified is False
        assert "installable" in result.reason_not_verified.lower()

    def test_summary_reads_cleanly(self):
        r = VerificationResult(
            verified=True, passed=10, failed=2, errors=0, skipped=1,
        )
        s = r.summary()
        assert "10 passed" in s and "2 failed" in s and "83%" in s

    def test_not_verified_summary(self):
        r = VerificationResult(
            verified=False, reason_not_verified="pip failed",
        )
        assert r.summary() == "NOT VERIFIED: pip failed"

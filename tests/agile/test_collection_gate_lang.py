"""Language-aware collection gate — non-Python paths.

Motivated by the 2026-07-22 TS acceptance run: two failing tests merged
to integration silently because check_collection was pytest-only and a
package.json repo made it a no-op.
"""

from __future__ import annotations

from pathlib import Path

from orgos.agile.collection_gate import (
    check_collection, gate_command, _check_test_cmd,
)


def _node_repo(tmp_path: Path, test_script: str) -> Path:
    (tmp_path / "package.json").write_text(
        '{"name": "x", "version": "0.0.0", "private": true,'
        f' "scripts": {{"test": "{test_script}"}}}}'
    )
    return tmp_path


class TestGateCommand:
    def test_python_repo_reports_pytest(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text('[project]\nname="x"\nversion="0"\n')
        assert gate_command(tmp_path) == "pytest --collect-only"

    def test_unknown_repo_reports_pytest(self, tmp_path):
        assert gate_command(tmp_path) == "pytest --collect-only"

    def test_node_repo_reports_npm_test(self, tmp_path):
        _node_repo(tmp_path, "true")
        assert gate_command(tmp_path) == "npm test"


class TestNodeGate:
    def test_passing_test_cmd_is_ok(self, tmp_path):
        _node_repo(tmp_path, "true")
        ok, broken, _ = _check_test_cmd(tmp_path, "exit 0", timeout=10)
        assert ok is True
        assert broken == []

    def test_failing_test_cmd_blocks(self, tmp_path):
        _node_repo(tmp_path, "false")
        ok, broken, tail = _check_test_cmd(
            tmp_path, "echo '1 test failed'; exit 1", timeout=10,
        )
        assert ok is False
        assert "1 test failed" in tail

    def test_missing_toolchain_fails_open(self, tmp_path):
        """exit 127 / command not found = toolchain absent in this
        worktree (e.g. no node_modules) — infrastructure, not broken code."""
        _node_repo(tmp_path, "definitely-not-a-real-binary-xyz")
        ok, _, _ = _check_test_cmd(
            tmp_path, "definitely-not-a-real-binary-xyz", timeout=10,
        )
        assert ok is True

    def test_empty_test_cmd_fails_open(self, tmp_path):
        ok, _, _ = _check_test_cmd(tmp_path, "", timeout=10)
        assert ok is True

    def test_check_collection_dispatches_to_node(self, tmp_path):
        """A package.json repo must NOT silently pass through the pytest
        path — the failing `npm test` here has to block."""
        repo = _node_repo(tmp_path, "node -e 'process.exit(1)'")
        ok, _, _ = check_collection(repo, timeout=10)
        assert ok is False

    def test_check_collection_node_green(self, tmp_path):
        repo = _node_repo(tmp_path, "node -e 'process.exit(0)'")
        ok, _, _ = check_collection(repo, timeout=10)
        assert ok is True

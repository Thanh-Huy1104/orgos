"""Tests for LLM-driven merge conflict resolver (Fix §B6)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from orgos.agile.merge_resolver import (
    _classify, try_resolve_rebase_conflicts,
)


class TestClassify:
    def test_init_py(self):
        assert _classify("quant/__init__.py") == "init_py"
        assert _classify("__init__.py") == "init_py"

    def test_markdown(self):
        assert _classify("docs/README.md") == "markdown_or_text"
        assert _classify("wiki/DECISIONS.md") == "markdown_or_text"
        assert _classify("notes.txt") == "markdown_or_text"

    def test_test_file(self):
        assert _classify("tests/test_foo.py") == "test_file"
        assert _classify("tests/sub/test_bar.py") == "test_file"

    def test_other(self):
        assert _classify("app.py") == "other"
        assert _classify("quant/strategies/momentum.py") == "other"


@pytest.fixture
def repo_with_conflict(tmp_path):
    """Set up a repo mid-rebase with a conflict in an __init__.py."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / "quant").mkdir()
    (tmp_path / "quant" / "__init__.py").write_text("# base\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)

    # Branch A adds an import
    subprocess.run(["git", "checkout", "-qb", "branch-a"], cwd=tmp_path, check=True)
    (tmp_path / "quant" / "__init__.py").write_text("# base\nfrom .a import A\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "add A"], cwd=tmp_path, check=True)

    # Back to main, branch B adds a different import
    subprocess.run(["git", "checkout", "-q", "master"], cwd=tmp_path, check=False)
    subprocess.run(["git", "checkout", "-q", "main"], cwd=tmp_path, check=False)
    # Whichever default branch — figure it out
    r = subprocess.run(
        ["git", "branch", "--show-current"], cwd=tmp_path,
        capture_output=True, text=True, check=True,
    )
    default_branch = r.stdout.strip()
    (tmp_path / "quant" / "__init__.py").write_text("# base\nfrom .b import B\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "add B"], cwd=tmp_path, check=True)

    # Try to rebase branch-a onto default — will conflict
    subprocess.run(["git", "checkout", "-q", "branch-a"], cwd=tmp_path, check=True)
    r = subprocess.run(
        ["git", "rebase", default_branch], cwd=tmp_path,
        capture_output=True, text=True,
    )
    # We EXPECT the rebase to fail (both sides modified quant/__init__.py)
    assert r.returncode != 0
    return tmp_path


class TestResolver:
    def test_bail_when_llm_declines(self, repo_with_conflict):
        # A spawner that returns garbage — LLM couldn't resolve
        def fake_spawner(*, prompt, model):
            result = MagicMock()
            result.tasks_output = [MagicMock(raw="hello world")]  # no valid resolution
            return result

        # Actually — our resolver rejects when output still contains markers.
        # A plain-text "hello world" reply would be accepted since it has no
        # markers. So let's craft a spawner that produces a WORTHLESS but
        # non-empty output — the resolver accepts it. To force decline we
        # need the LLM to return output containing markers.
        def marker_spawner(*, prompt, model):
            result = MagicMock()
            result.tasks_output = [MagicMock(raw="<<<<<<< HEAD\nxxx\n=======\nyyy\n>>>>>>>")]
            return result

        ok, msg = try_resolve_rebase_conflicts(
            repo_with_conflict, model="mock", spawner=marker_spawner,
        )
        assert ok is False
        assert "LLM couldn't resolve" in msg

    def test_resolves_init_py_conflict(self, repo_with_conflict):
        def resolving_spawner(*, prompt, model):
            result = MagicMock()
            result.tasks_output = [
                MagicMock(raw="# base\nfrom .a import A\nfrom .b import B\n"),
            ]
            return result

        ok, msg = try_resolve_rebase_conflicts(
            repo_with_conflict, model="mock", spawner=resolving_spawner,
        )
        assert ok is True
        assert "resolved 1 files" in msg
        content = (repo_with_conflict / "quant" / "__init__.py").read_text()
        assert "from .a import A" in content
        assert "from .b import B" in content
        assert "<<<<<<<" not in content

    def test_bail_on_unsafe_file_class(self, tmp_path):
        """When conflict is in a non-safe file (e.g. a real .py module),
        the resolver declines without ever calling the LLM."""
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
        (tmp_path / "app.py").write_text("def x(): pass\n")
        subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
        subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)
        subprocess.run(["git", "checkout", "-qb", "a"], cwd=tmp_path, check=True)
        (tmp_path / "app.py").write_text("def x(): return 1\n")
        subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
        subprocess.run(["git", "commit", "-qm", "a"], cwd=tmp_path, check=True)

        r = subprocess.run(
            ["git", "branch", "--show-current"], cwd=tmp_path,
            capture_output=True, text=True, check=True,
        )
        # Switch back to master/main
        subprocess.run(
            ["git", "checkout", "-q", "master"], cwd=tmp_path, check=False,
        )
        subprocess.run(
            ["git", "checkout", "-q", "main"], cwd=tmp_path, check=False,
        )
        r = subprocess.run(
            ["git", "branch", "--show-current"], cwd=tmp_path,
            capture_output=True, text=True, check=True,
        )
        default_branch = r.stdout.strip()
        (tmp_path / "app.py").write_text("def x(): return 2\n")
        subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
        subprocess.run(["git", "commit", "-qm", "b"], cwd=tmp_path, check=True)
        subprocess.run(["git", "checkout", "-q", "a"], cwd=tmp_path, check=True)
        subprocess.run(
            ["git", "rebase", default_branch], cwd=tmp_path,
            capture_output=True, text=True,
        )
        # Now app.py is in conflict — not a safe file class
        # Spawner should never be called
        spawner_called = []
        def sentinel_spawner(*, prompt, model):
            spawner_called.append(True)
            raise AssertionError("should not be called for unsafe file class")

        ok, msg = try_resolve_rebase_conflicts(
            tmp_path, model="mock", spawner=sentinel_spawner,
        )
        assert ok is False
        assert "unsafe" in msg
        assert spawner_called == []

"""Shared fixtures for agile-team tests.

Most fixtures live here so individual test files stay focused. The
fixture_repo() factory builds an isolated git repo on disk that tests
can mutate without touching the orgos worktree.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def fixture_repo(tmp_path: Path) -> Path:
    """Build a minimal git repo in tmp_path. Caller can mutate freely."""
    repo = tmp_path / "fixture-repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "README.md").write_text("# fixture\n")
    (repo / "src.py").write_text("def greet():\n    return 'hi'\n")
    (repo / "test_src.py").write_text(
        "from src import greet\n\n"
        "def test_greet():\n    assert greet() == 'hi'\n"
    )
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    return repo

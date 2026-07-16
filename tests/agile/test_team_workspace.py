"""Tests for TeamWorkspace — create, open, reset, list."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from orgos.agile.team_workspace import (
    TeamWorkspace, TeamWorkspaceExists, TeamWorkspaceMissing, list_team_ids,
)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A tiny git repo with a single commit."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.local"],
                    cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "test"],
                    cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("# test\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)
    return tmp_path


class TestCreate:
    def test_creates_workspace_dirs(self, repo):
        ws = TeamWorkspace.create("t1", repo, goal="test", model="m")
        assert ws.root.exists()
        assert ws.worktree.exists()
        assert ws.board_dir.exists()
        assert ws.wiki_dir.exists()
        assert ws.audit_dir.exists()
        assert ws.manifest_path.exists()

    def test_creates_branch_off_head(self, repo):
        ws = TeamWorkspace.create("t1", repo, goal="test", model="m")
        m = ws.manifest()
        assert m.branch == "team/t1"
        assert m.baseline_sha  # should be captured

    def test_baseline_gitignore_committed(self, repo):
        ws = TeamWorkspace.create("t1", repo, goal="test", model="m")
        assert (ws.worktree / ".gitignore").exists()
        assert "snapshot.json" in (ws.worktree / ".gitignore").read_text()

    def test_duplicate_team_id_raises(self, repo):
        TeamWorkspace.create("t1", repo, goal="test", model="m")
        with pytest.raises(TeamWorkspaceExists):
            TeamWorkspace.create("t1", repo, goal="test", model="m")


class TestOpen:
    def test_reopens_existing(self, repo):
        TeamWorkspace.create("t1", repo, goal="my goal", model="m")
        ws = TeamWorkspace.open("t1", repo)
        assert ws.manifest().goal == "my goal"

    def test_open_missing_raises(self, repo):
        with pytest.raises(TeamWorkspaceMissing):
            TeamWorkspace.open("nope", repo)


class TestHeadTracking:
    def test_head_advances_after_commit(self, repo):
        ws = TeamWorkspace.create("t1", repo, goal="test", model="m")
        baseline = ws.manifest().baseline_sha
        (ws.worktree / "new.txt").write_text("hi")
        subprocess.run(["git", "add", "-A"], cwd=ws.worktree, check=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t",
                        "commit", "-qm", "add new"], cwd=ws.worktree, check=True)
        assert ws.head_advanced_since(baseline)

    def test_diff_since_returns_new_file(self, repo):
        ws = TeamWorkspace.create("t1", repo, goal="test", model="m")
        baseline = ws.manifest().baseline_sha
        (ws.worktree / "new.txt").write_text("hi")
        subprocess.run(["git", "add", "-A"], cwd=ws.worktree, check=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t",
                        "commit", "-qm", "add new"], cwd=ws.worktree, check=True)
        diff = ws.diff_since(baseline)
        assert "new.txt" in diff


class TestListAndReset:
    def test_list_team_ids(self, repo):
        assert list_team_ids(repo) == []
        TeamWorkspace.create("t1", repo, goal="g", model="m")
        TeamWorkspace.create("t2", repo, goal="g", model="m")
        assert set(list_team_ids(repo)) == {"t1", "t2"}

    def test_reset_removes_workspace(self, repo):
        ws = TeamWorkspace.create("t1", repo, goal="g", model="m")
        ws.reset()
        assert not ws.exists()
        assert list_team_ids(repo) == []

    def test_reset_then_recreate_works(self, repo):
        ws = TeamWorkspace.create("t1", repo, goal="g1", model="m")
        ws.reset()
        ws2 = TeamWorkspace.create("t1", repo, goal="g2", model="m")
        assert ws2.manifest().goal == "g2"

"""Tests for TeamWorkspace — create, open, reset, list."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from orgos.agile.team_workspace import (
    TeamWorkspace, TeamWorkspaceExists, TeamWorkspaceMissing, list_team_ids,
)

ROLES = ("po", "scrum_master", "architect", "test", "devsecops")


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
        assert m.branch == "team/t1/integration"
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


class TestPerAgentWorktrees:
    def test_agent_dir_shape(self, repo):
        ws = TeamWorkspace.create("t1", repo, goal="g", model="m")
        for role in ROLES:
            ws.ensure_agent_workspace(role)
            assert ws.agent_dir(role).exists()
            assert ws.agent_worktree(role).exists()

    def test_integration_worktree_created(self, repo):
        ws = TeamWorkspace.create("t1", repo, goal="g", model="m")
        assert ws.integration_worktree.exists()
        assert ws.integration_branch == "team/t1/integration"

    def test_each_agent_has_own_branch(self, repo):
        ws = TeamWorkspace.create("t1", repo, goal="g", model="m")
        for role in ROLES:
            ws.ensure_agent_workspace(role)
            branches = subprocess.run(
                ["git", "branch", "--format=%(refname:short)"],
                cwd=repo, capture_output=True, text=True,
            ).stdout.strip().splitlines()
            assert f"team/t1/agent/{role}" in branches

    def test_rerere_enabled_in_agent_worktree(self, repo):
        ws = TeamWorkspace.create("t1", repo, goal="g", model="m")
        ws.ensure_agent_workspace("architect")
        result = subprocess.run(
            ["git", "config", "--get", "rerere.enabled"],
            cwd=ws.agent_worktree("architect"),
            capture_output=True, text=True,
        )
        assert result.stdout.strip() == "true"

    def test_baseline_test_result_recorded(self, repo):
        ws = TeamWorkspace.create("t1", repo, goal="g", model="m")
        # Even if there are no tests to run, baseline is a dict with a status
        assert isinstance(ws.baseline_test_result, dict)
        assert "status" in ws.baseline_test_result


class TestNDevAgentInstances:
    """N>1 delivery agents of the same role each get their own worktree +
    branch. Enables real Scrum team-scale runs (3-9 devs)."""

    def test_instance_0_matches_historical_layout(self, repo):
        ws = TeamWorkspace.create("t1", repo, goal="g", model="m")
        ws.ensure_agent_workspace("architect", 0)
        # Historical: agents/architect/worktree (no -0 suffix)
        assert ws.agent_dir("architect", 0) == ws.agents_root / "architect"
        assert ws.agent_worktree("architect", 0).exists()
        assert ws.agent_branch("architect", 0) == "team/t1/agent/architect"

    def test_instance_N_uses_suffixed_layout(self, repo):
        ws = TeamWorkspace.create("t1", repo, goal="g", model="m")
        ws.ensure_agent_workspace("architect", 0)
        ws.ensure_agent_workspace("architect", 1)
        ws.ensure_agent_workspace("architect", 2)
        for i in (0, 1, 2):
            wt = ws.agent_worktree("architect", i)
            assert wt.exists(), f"instance {i} worktree missing: {wt}"
        # Independent branches — no sharing
        branches = subprocess.run(
            ["git", "branch", "--format=%(refname:short)"],
            cwd=repo, capture_output=True, text=True,
        ).stdout.strip().splitlines()
        assert "team/t1/agent/architect" in branches
        assert "team/t1/agent/architect-1" in branches
        assert "team/t1/agent/architect-2" in branches

    def test_reset_cleans_all_instances(self, repo):
        ws = TeamWorkspace.create("t1", repo, goal="g", model="m")
        for i in range(3):
            ws.ensure_agent_workspace("architect", i)
            ws.ensure_agent_workspace("test", i)
        ws.reset()
        # All 3×2 = 6 delivery worktrees gone + all 6 branches gone
        branches = subprocess.run(
            ["git", "branch", "--format=%(refname:short)"],
            cwd=repo, capture_output=True, text=True,
        ).stdout.strip().splitlines()
        for r in ("architect", "test"):
            assert f"team/t1/agent/{r}" not in branches
            for i in (1, 2):
                assert f"team/t1/agent/{r}-{i}" not in branches

    def test_independent_worktrees_do_not_share_working_dir(self, repo):
        """Each instance's worktree must be a physically separate directory."""
        ws = TeamWorkspace.create("t1", repo, goal="g", model="m")
        ws.ensure_agent_workspace("architect", 0)
        ws.ensure_agent_workspace("architect", 1)
        wt0 = ws.agent_worktree("architect", 0)
        wt1 = ws.agent_worktree("architect", 1)
        assert wt0 != wt1
        # Write different files in each — verify they don't collide
        (wt0 / "instance0.txt").write_text("only in 0")
        (wt1 / "instance1.txt").write_text("only in 1")
        assert (wt0 / "instance0.txt").exists()
        assert not (wt0 / "instance1.txt").exists()
        assert (wt1 / "instance1.txt").exists()
        assert not (wt1 / "instance0.txt").exists()

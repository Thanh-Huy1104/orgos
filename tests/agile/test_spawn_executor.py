"""Tests for SpawnCodingExecutor — the non-opencode default coding executor."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from orgos.agile.spawn_executor import SpawnCodingExecutor


class FakeStory:
    issue_id = "S1"
    title = "add ping"
    type = "feature"
    body = "add ping() returning 'pong'"
    files_to_touch = ["app.py"]


@pytest.fixture
def repo(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("init")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)
    return tmp_path


def _baseline(repo: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True,
    ).stdout.strip()


class TestSpawnCodingExecutorSuccess:
    def test_success_when_spawn_lands_a_commit(self, repo, monkeypatch):
        baseline = _baseline(repo)

        def fake_spawn(role, brief, run_budget_tokens=1_200_000):
            # Simulate the LLM landing a commit
            (repo / "app.py").write_text("def ping(): return 'pong'\n")
            subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
            subprocess.run(
                ["git", "-c", "user.name=x", "-c", "user.email=x@x",
                 "commit", "-qm", "feat: ping"],
                cwd=repo, check=True,
            )
            fake_result = MagicMock()
            fake_result.token_usage = {"prompt_tokens": 100, "completion_tokens": 50}
            fake_result.tasks_output = [MagicMock(raw='{"role":"architect","status":"completed","summary":"added ping"}')]
            return fake_result

        # Also stub the role factory to avoid CrewAI setup
        monkeypatch.setattr("orgos.agile.spawn_executor.spawn", fake_spawn)
        monkeypatch.setattr("orgos.agile.spawn_executor.architect_role",
                            lambda **kw: MagicMock(mcp_servers=[]))

        ex = SpawnCodingExecutor(
            model="deepseek/deepseek-chat",
            baseline_sha_provider=lambda: baseline,
        )
        result = ex.run_story(
            worktree=repo, story=FakeStory(),
            persona_scaffold="", session_id="architect",
        )
        assert result.success is True
        assert result.commit_sha != baseline
        assert "app.py" in result.files_touched
        assert result.tokens_input == 100
        assert result.tokens_output == 50
        assert "added ping" in result.learnings


class TestSpawnCodingExecutorFailure:
    def test_no_commit_returns_failure(self, repo, monkeypatch):
        baseline = _baseline(repo)

        def fake_spawn(role, brief, run_budget_tokens=1_200_000):
            fake_result = MagicMock()
            fake_result.token_usage = {}
            fake_result.tasks_output = [MagicMock(raw='no commit made')]
            return fake_result

        monkeypatch.setattr("orgos.agile.spawn_executor.spawn", fake_spawn)
        monkeypatch.setattr("orgos.agile.spawn_executor.architect_role",
                            lambda **kw: MagicMock(mcp_servers=[]))

        ex = SpawnCodingExecutor(
            model="m",
            baseline_sha_provider=lambda: baseline,
        )
        result = ex.run_story(
            worktree=repo, story=FakeStory(),
            persona_scaffold="", session_id="architect",
        )
        assert result.success is False
        assert "no commit" in result.error.lower()

    def test_spawn_exception_returns_failure(self, repo, monkeypatch):
        baseline = _baseline(repo)

        def fake_spawn(role, brief, run_budget_tokens=1_200_000):
            raise RuntimeError("crewai boom")

        monkeypatch.setattr("orgos.agile.spawn_executor.spawn", fake_spawn)
        monkeypatch.setattr("orgos.agile.spawn_executor.architect_role",
                            lambda **kw: MagicMock(mcp_servers=[]))

        ex = SpawnCodingExecutor(
            model="m",
            baseline_sha_provider=lambda: baseline,
        )
        result = ex.run_story(
            worktree=repo, story=FakeStory(),
            persona_scaffold="", session_id="architect",
        )
        assert result.success is False
        assert "spawn_exception" in result.error
        assert "crewai boom" in result.error


class TestSpawnCodingExecutorRoleRouting:
    def test_test_role_used_when_session_id_is_test(self, repo, monkeypatch):
        captured = {}
        def fake_test_role(**kw):
            captured["called"] = "test_role"
            return MagicMock(mcp_servers=[])
        def fake_arch_role(**kw):
            captured["called"] = "architect_role"
            return MagicMock(mcp_servers=[])

        def fake_spawn(role, brief, run_budget_tokens=1_200_000):
            r = MagicMock()
            r.token_usage = {}
            r.tasks_output = []
            return r

        monkeypatch.setattr("orgos.agile.spawn_executor.spawn", fake_spawn)
        monkeypatch.setattr("orgos.agile.spawn_executor.architect_role", fake_arch_role)
        monkeypatch.setattr("orgos.agile.spawn_executor.test_role", fake_test_role)

        ex = SpawnCodingExecutor(model="m", baseline_sha_provider=lambda: _baseline(repo))
        ex.run_story(worktree=repo, story=FakeStory(), persona_scaffold="",
                     session_id="test")
        assert captured["called"] == "test_role"

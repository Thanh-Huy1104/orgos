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


class TestArchDoDAutoWrite:
    """When an architecture story commits code but doesn't touch
    wiki/DECISIONS.md, the executor auto-writes a compliant stub entry
    (author + timestamp + source citing the issue_id) and amends with a
    follow-up commit. Removes LLM unreliability from the DoD path.
    """

    def _arch_story(self):
        s = FakeStory()
        s.issue_id = "S-ARCH-001"
        s.type = "architecture"
        s.title = "Extract Note data model"
        return s

    def test_auto_writes_wiki_stub_when_missing(self, repo, monkeypatch):
        baseline = _baseline(repo)

        def fake_spawn(role, brief, run_budget_tokens=1_200_000):
            # LLM committed code but did NOT touch wiki/DECISIONS.md
            (repo / "app.py").write_text("class Note: pass\n")
            subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
            subprocess.run(
                ["git", "-c", "user.name=x", "-c", "user.email=x@x",
                 "commit", "-qm", "architecture: extract Note"],
                cwd=repo, check=True,
            )
            r = MagicMock()
            r.token_usage = {}
            r.tasks_output = [MagicMock(raw='{"summary": "extracted Note class"}')]
            return r

        monkeypatch.setattr("orgos.agile.spawn_executor.spawn", fake_spawn)
        monkeypatch.setattr("orgos.agile.spawn_executor.architect_role",
                            lambda **kw: MagicMock(mcp_servers=[]))

        ex = SpawnCodingExecutor(
            model="m", baseline_sha_provider=lambda: baseline,
        )
        result = ex.run_story(
            worktree=repo, story=self._arch_story(),
            persona_scaffold="", session_id="architect",
        )
        assert result.success is True
        # Wiki entry was auto-written
        decisions = (repo / "wiki" / "DECISIONS.md").read_text()
        assert "S-ARCH-001" in decisions
        assert "author: architect-agent" in decisions
        assert "timestamp:" in decisions
        assert "source: S-ARCH-001" in decisions
        # DoD gate would now accept it
        from orgos.mcps.wiki_mcp import decisions_cite_source
        assert decisions_cite_source(decisions, "S-ARCH-001")
        # A follow-up commit landed (result.commit_sha != first commit sha)
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo,
            capture_output=True, text=True,
        ).stdout.strip()
        assert result.commit_sha == head

    def test_leaves_alone_if_wiki_entry_already_compliant(self, repo, monkeypatch):
        baseline = _baseline(repo)
        # LLM writes both the code AND a compliant wiki entry itself
        (repo / "wiki").mkdir(exist_ok=True)
        (repo / "wiki" / "DECISIONS.md").write_text(
            "## Extract Note\n"
            "author: architect-agent\n"
            "timestamp: 2026-07-17T00:00:00Z\n"
            "source: S-ARCH-001\n\n"
            "Split Note out of app.py for reuse.\n"
        )

        def fake_spawn(role, brief, run_budget_tokens=1_200_000):
            (repo / "app.py").write_text("class Note: pass\n")
            subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
            subprocess.run(
                ["git", "-c", "user.name=x", "-c", "user.email=x@x",
                 "commit", "-qm", "architecture + wiki"],
                cwd=repo, check=True,
            )
            r = MagicMock()
            r.token_usage = {}
            r.tasks_output = []
            return r

        monkeypatch.setattr("orgos.agile.spawn_executor.spawn", fake_spawn)
        monkeypatch.setattr("orgos.agile.spawn_executor.architect_role",
                            lambda **kw: MagicMock(mcp_servers=[]))

        ex = SpawnCodingExecutor(
            model="m", baseline_sha_provider=lambda: baseline,
        )
        pre = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo,
            capture_output=True, text=True,
        ).stdout.strip()
        result = ex.run_story(
            worktree=repo, story=self._arch_story(),
            persona_scaffold="", session_id="architect",
        )
        # No extra commit should have been added since the wiki was already compliant
        post = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo,
            capture_output=True, text=True,
        ).stdout.strip()
        assert result.commit_sha == post
        # Only the LLM's commit exists (no auto-DoD commit stacked on top)
        log = subprocess.run(
            ["git", "log", "--oneline", f"{baseline}..HEAD"], cwd=repo,
            capture_output=True, text=True,
        ).stdout
        assert "docs(dod)" not in log, f"unexpected auto-DoD commit: {log}"

    def test_non_architecture_stories_untouched(self, repo, monkeypatch):
        baseline = _baseline(repo)

        def fake_spawn(role, brief, run_budget_tokens=1_200_000):
            (repo / "app.py").write_text("def foo(): pass\n")
            subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
            subprocess.run(
                ["git", "-c", "user.name=x", "-c", "user.email=x@x",
                 "commit", "-qm", "feature: add foo"],
                cwd=repo, check=True,
            )
            r = MagicMock()
            r.token_usage = {}
            r.tasks_output = []
            return r

        monkeypatch.setattr("orgos.agile.spawn_executor.spawn", fake_spawn)
        monkeypatch.setattr("orgos.agile.spawn_executor.architect_role",
                            lambda **kw: MagicMock(mcp_servers=[]))

        story = FakeStory()
        story.type = "feature"  # NOT architecture
        ex = SpawnCodingExecutor(
            model="m", baseline_sha_provider=lambda: baseline,
        )
        ex.run_story(
            worktree=repo, story=story,
            persona_scaffold="", session_id="architect",
        )
        # Feature stories should NOT trigger any wiki auto-write
        assert not (repo / "wiki" / "DECISIONS.md").exists()


class TestWipAutoCommitFallback:
    """When the LLM writes files but skips `git commit`, the executor should
    auto-commit them with a WIP: prefix and return success. Turns 'LLM
    forgot the commit step' from total loss into partial delivery.
    """
    def test_wip_autocommit_when_llm_wrote_files_but_did_not_commit(
        self, repo, monkeypatch,
    ):
        baseline = _baseline(repo)

        def fake_spawn(role, brief, run_budget_tokens=1_200_000):
            # Simulate: LLM wrote a file but did NOT run `git commit`.
            (repo / "app.py").write_text("def ping(): return 'pong'\n")
            r = MagicMock()
            r.token_usage = {"prompt_tokens": 100, "completion_tokens": 50}
            r.tasks_output = [MagicMock(raw='{"summary": "wrote ping but forgot commit"}')]
            return r

        monkeypatch.setattr("orgos.agile.spawn_executor.spawn", fake_spawn)
        monkeypatch.setattr("orgos.agile.spawn_executor.architect_role",
                            lambda **kw: MagicMock(mcp_servers=[]))

        ex = SpawnCodingExecutor(
            model="m", baseline_sha_provider=lambda: baseline,
        )
        result = ex.run_story(
            worktree=repo, story=FakeStory(),
            persona_scaffold="", session_id="architect",
        )
        assert result.success is True, f"expected auto-commit fallback, got error={result.error}"
        assert result.commit_sha != baseline
        assert "app.py" in result.files_touched
        assert "auto-committed" in result.learnings.lower()

    def test_no_fallback_when_no_uncommitted_changes(self, repo, monkeypatch):
        baseline = _baseline(repo)

        def fake_spawn(role, brief, run_budget_tokens=1_200_000):
            # LLM didn't write anything AND didn't commit
            r = MagicMock()
            r.token_usage = {}
            r.tasks_output = [MagicMock(raw='I gave up')]
            return r

        monkeypatch.setattr("orgos.agile.spawn_executor.spawn", fake_spawn)
        monkeypatch.setattr("orgos.agile.spawn_executor.architect_role",
                            lambda **kw: MagicMock(mcp_servers=[]))

        ex = SpawnCodingExecutor(
            model="m", baseline_sha_provider=lambda: baseline,
        )
        result = ex.run_story(
            worktree=repo, story=FakeStory(),
            persona_scaffold="", session_id="architect",
        )
        assert result.success is False
        assert "no commit" in result.error.lower()

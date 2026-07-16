"""Tests for CodingExecutor protocol + OpenCodeExecutor."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from orgos.agile.coding_executor import (
    CodingExecutor, ExecutionResult, OpenCodeExecutor,
)


class TestExecutionResult:
    def test_defaults(self):
        r = ExecutionResult(success=True, commit_sha="abc123")
        assert r.success is True
        assert r.commit_sha == "abc123"
        assert r.files_touched == []
        assert r.tokens_input == 0


class TestOpenCodeExecutorProtocolConformance:
    def test_implements_protocol(self):
        ex = OpenCodeExecutor(model="deepseek/deepseek-chat")
        # Protocol is a duck-typing check; just verify the methods exist.
        assert hasattr(ex, "run_story")
        assert hasattr(ex, "spawn_subagent")


class FakeStory:
    def __init__(self):
        self.issue_id = "S-001"
        self.title = "Add ping"
        self.body = "Add ping() to app.py returning 'pong'"
        self.type = "feature"
        self.priority = 5
        self.files_to_touch = ["app.py"]


class TestOpenCodeRunStory:
    """Uses a mocked subprocess so we don't invoke real opencode."""

    def test_success_when_subprocess_exits_zero_and_commit_lands(
        self, tmp_path, monkeypatch,
    ):
        # Fake worktree with a git repo and an initial commit
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
        (tmp_path / "README.md").write_text("init")
        subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
        subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)

        baseline_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=tmp_path,
            capture_output=True, text=True,
        ).stdout.strip()

        # Simulate opencode landing a commit by making it happen ourselves inside the fake
        def fake_run(cmd, **kw):
            # Pretend opencode ran successfully and made a commit
            if cmd[0] == "opencode":
                (tmp_path / "app.py").write_text("def ping(): return 'pong'\n")
                subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
                subprocess.run(
                    ["git", "-c", "user.name=oc", "-c", "user.email=oc@oc",
                     "commit", "-qm", "feat: add ping"],
                    cwd=tmp_path, check=True,
                )
                r = MagicMock()
                r.returncode = 0
                r.stdout = "session:ok\n"
                r.stderr = ""
                return r
            return subprocess.run(cmd, **kw)  # real for other commands

        monkeypatch.setattr("orgos.agile.coding_executor.subprocess.run", fake_run)

        ex = OpenCodeExecutor(model="deepseek/deepseek-chat",
                               baseline_sha_provider=lambda: baseline_sha)
        result = ex.run_story(
            worktree=tmp_path,
            story=FakeStory(),
            persona_scaffold="you are the architect",
            session_id="arch-1",
        )
        assert result.success is True
        assert result.commit_sha != baseline_sha
        assert "app.py" in result.files_touched

    def test_failure_when_no_commit_landed(self, tmp_path, monkeypatch):
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
        (tmp_path / "README.md").write_text("init")
        subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
        subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)

        baseline_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=tmp_path,
            capture_output=True, text=True,
        ).stdout.strip()

        def fake_run(cmd, **kw):
            if cmd[0] == "opencode":
                r = MagicMock()
                r.returncode = 0
                r.stdout = ""
                r.stderr = ""
                return r
            return subprocess.run(cmd, **kw)

        monkeypatch.setattr("orgos.agile.coding_executor.subprocess.run", fake_run)

        ex = OpenCodeExecutor(model="m",
                               baseline_sha_provider=lambda: baseline_sha)
        result = ex.run_story(
            worktree=tmp_path,
            story=FakeStory(),
            persona_scaffold="you are the architect",
            session_id="arch-2",
        )
        assert result.success is False
        assert "no commit" in result.error.lower()

    def test_timeout(self, tmp_path, monkeypatch):
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
        (tmp_path / "README.md").write_text("init")
        subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
        subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)

        baseline_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=tmp_path,
            capture_output=True, text=True,
        ).stdout.strip()

        def fake_run(cmd, **kw):
            if cmd[0] == "opencode":
                raise subprocess.TimeoutExpired(cmd, kw.get("timeout", 60))
            return subprocess.run(cmd, **kw)

        monkeypatch.setattr("orgos.agile.coding_executor.subprocess.run", fake_run)

        ex = OpenCodeExecutor(model="m", timeout_seconds=1,
                               baseline_sha_provider=lambda: baseline_sha)
        result = ex.run_story(
            worktree=tmp_path,
            story=FakeStory(),
            persona_scaffold="scaf",
            session_id="arch-3",
        )
        assert result.success is False
        assert "timeout" in result.error.lower()

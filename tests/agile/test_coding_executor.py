"""Tests for CodingExecutor protocol + ClaudeCodeExecutor."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from orgos.agile.coding_executor import (
    CodingExecutor, ClaudeCodeExecutor, CopilotCliExecutor, ExecutionResult,
)


class TestExecutionResult:
    def test_defaults(self):
        r = ExecutionResult(success=True, commit_sha="abc123")
        assert r.success is True
        assert r.commit_sha == "abc123"
        assert r.files_touched == []
        assert r.tokens_input == 0


class TestClaudeCodeExecutorProtocolConformance:
    def test_implements_protocol(self):
        ex = ClaudeCodeExecutor()
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


class TestClaudeCodeRunStory:
    """Uses a mocked subprocess so we don't invoke real claude."""

    def test_success_when_subprocess_exits_zero_and_commit_lands(
        self, tmp_path, monkeypatch,
    ):
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
            if cmd[0] == "claude":
                (tmp_path / "app.py").write_text("def ping(): return 'pong'\n")
                subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
                subprocess.run(
                    ["git", "-c", "user.name=cc", "-c", "user.email=cc@cc",
                     "commit", "-qm", "feat: add ping"],
                    cwd=tmp_path, check=True,
                )
                r = MagicMock()
                r.returncode = 0
                r.stdout = "did it\n"
                r.stderr = ""
                return r
            return subprocess.run(cmd, **kw)

        monkeypatch.setattr("orgos.agile.coding_executor.subprocess.run", fake_run)

        ex = ClaudeCodeExecutor(baseline_sha_provider=lambda: baseline_sha)
        result = ex.run_story(
            worktree=tmp_path, story=FakeStory(),
            persona_scaffold="you are the architect",
            session_id="architect",
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
            if cmd[0] == "claude":
                r = MagicMock()
                r.returncode = 0
                r.stdout = ""
                r.stderr = ""
                return r
            return subprocess.run(cmd, **kw)

        monkeypatch.setattr("orgos.agile.coding_executor.subprocess.run", fake_run)

        ex = ClaudeCodeExecutor(baseline_sha_provider=lambda: baseline_sha)
        result = ex.run_story(
            worktree=tmp_path, story=FakeStory(),
            persona_scaffold="scaf", session_id="architect",
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
            if cmd[0] == "claude":
                raise subprocess.TimeoutExpired(cmd, kw.get("timeout", 60))
            return subprocess.run(cmd, **kw)

        monkeypatch.setattr("orgos.agile.coding_executor.subprocess.run", fake_run)

        ex = ClaudeCodeExecutor(
            timeout_seconds=1, baseline_sha_provider=lambda: baseline_sha,
        )
        result = ex.run_story(
            worktree=tmp_path, story=FakeStory(),
            persona_scaffold="scaf", session_id="architect",
        )
        assert result.success is False
        assert "timeout" in result.error.lower()

    def test_binary_not_found(self, tmp_path, monkeypatch):
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
            if cmd[0] == "claude":
                raise FileNotFoundError("claude")
            return subprocess.run(cmd, **kw)

        monkeypatch.setattr("orgos.agile.coding_executor.subprocess.run", fake_run)

        ex = ClaudeCodeExecutor(baseline_sha_provider=lambda: baseline_sha)
        result = ex.run_story(
            worktree=tmp_path, story=FakeStory(),
            persona_scaffold="scaf", session_id="architect",
        )
        assert result.success is False
        assert "not found" in result.error.lower()


class TestCopilotCliExecutor:
    """CopilotCliExecutor mirrors ClaudeCodeExecutor; separate tests keep
    them independent so a change to one doesn't quietly break the other."""

    def _init_repo(self, tmp_path):
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
        (tmp_path / "README.md").write_text("init")
        subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
        subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=tmp_path,
            capture_output=True, text=True,
        ).stdout.strip()

    def test_success_lands_commit(self, tmp_path, monkeypatch):
        baseline_sha = self._init_repo(tmp_path)
        captured = {"argv": None, "env": None}

        def fake_run(cmd, **kw):
            if cmd[0] == "copilot":
                captured["argv"] = cmd
                captured["env"] = kw.get("env", {})
                (tmp_path / "app.py").write_text("def ping(): return 'pong'\n")
                subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
                subprocess.run(
                    ["git", "-c", "user.name=cp", "-c", "user.email=cp@cp",
                     "commit", "-qm", "feat: ping"],
                    cwd=tmp_path, check=True,
                )
                r = MagicMock()
                r.returncode = 0
                r.stdout = "\x1b[32mdid it\x1b[0m"  # with ANSI to test stripping
                r.stderr = ""
                return r
            return subprocess.run(cmd, **kw)

        monkeypatch.setattr("orgos.agile.coding_executor.subprocess.run", fake_run)
        # Ensure env vars don't leak from the host
        monkeypatch.delenv("COPILOT_MODEL", raising=False)
        monkeypatch.delenv("COPILOT_ALLOW_ALL", raising=False)

        ex = CopilotCliExecutor(baseline_sha_provider=lambda: baseline_sha)
        result = ex.run_story(
            worktree=tmp_path, story=FakeStory(),
            persona_scaffold="scaf", session_id="architect",
        )
        assert result.success is True
        assert result.commit_sha != baseline_sha
        assert "app.py" in result.files_touched
        # Default policy: --allow-all-tools present, no --deny-tool
        assert "--allow-all-tools" in captured["argv"]
        assert "--deny-tool" not in captured["argv"]
        # ANSI stripped from learnings
        assert "\x1b[" not in result.learnings
        assert "did it" in result.learnings
        # Prompt is passed via env for downstream tooling that wants it
        assert captured["env"].get("ORGOS_COPILOT_PROMPT")

    def test_allow_all_zero_uses_deny_tool_flags(self, tmp_path, monkeypatch):
        baseline_sha = self._init_repo(tmp_path)
        captured = {"argv": None}

        def fake_run(cmd, **kw):
            if cmd[0] == "copilot":
                captured["argv"] = cmd
                r = MagicMock()
                r.returncode = 0
                r.stdout = ""
                r.stderr = ""
                return r
            return subprocess.run(cmd, **kw)

        monkeypatch.setattr("orgos.agile.coding_executor.subprocess.run", fake_run)
        monkeypatch.setenv("COPILOT_ALLOW_ALL", "0")
        monkeypatch.setenv("COPILOT_MODEL", "claude-sonnet-4-6")

        ex = CopilotCliExecutor(baseline_sha_provider=lambda: baseline_sha)
        ex.run_story(
            worktree=tmp_path, story=FakeStory(),
            persona_scaffold="scaf", session_id="architect",
        )
        assert "--deny-tool" in captured["argv"]
        assert "shell" in captured["argv"]
        assert "write" in captured["argv"]
        assert "--allow-all-tools" not in captured["argv"]
        assert "--model" in captured["argv"]
        assert "claude-sonnet-4-6" in captured["argv"]

    def test_binary_not_found_gives_helpful_error(self, tmp_path, monkeypatch):
        baseline_sha = self._init_repo(tmp_path)

        def fake_run(cmd, **kw):
            if cmd[0] == "copilot":
                raise FileNotFoundError("copilot")
            return subprocess.run(cmd, **kw)

        monkeypatch.setattr("orgos.agile.coding_executor.subprocess.run", fake_run)

        ex = CopilotCliExecutor(baseline_sha_provider=lambda: baseline_sha)
        result = ex.run_story(
            worktree=tmp_path, story=FakeStory(),
            persona_scaffold="scaf", session_id="architect",
        )
        assert result.success is False
        assert "not found" in result.error.lower()
        assert "/login" in result.error  # helpful hint present

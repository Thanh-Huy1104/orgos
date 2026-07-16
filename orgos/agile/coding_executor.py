"""CodingExecutor — abstracts the coding-agent subprocess (default: OpenCode).

Only OpenCodeExecutor is implemented in v2. The Protocol shape leaves room
for AiderExecutor / ClaudeCodeExecutor without touching agent_loop.
"""

from __future__ import annotations

import subprocess as _subprocess_real
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Protocol


class _SubprocessProxy:
    """Thin proxy around the subprocess module so monkeypatch can replace
    ``orgos.agile.coding_executor.subprocess.run`` without affecting the
    real ``subprocess.run`` in other modules (they share the same module
    object otherwise, which causes infinite recursion in tests).
    """

    TimeoutExpired = _subprocess_real.TimeoutExpired
    DEVNULL = _subprocess_real.DEVNULL

    def run(self, *args, **kwargs):  # noqa: D102
        return _subprocess_real.run(*args, **kwargs)

    def check_output(self, *args, **kwargs):  # noqa: D102
        return _subprocess_real.check_output(*args, **kwargs)


subprocess = _SubprocessProxy()


@dataclass
class ExecutionResult:
    success: bool
    commit_sha: str = ""
    files_touched: list[str] = field(default_factory=list)
    learnings: str = ""
    tokens_input: int = 0
    tokens_output: int = 0
    wall_seconds: float = 0.0
    error: str = ""
    raw_stdout: str = ""
    raw_stderr: str = ""


class CodingExecutor(Protocol):
    """Runs one story's worth of work in a worktree; returns what happened."""

    def run_story(
        self, *,
        worktree: Path,
        story: Any,                 # Story from board_store (typed loosely to avoid circular import)
        persona_scaffold: str,
        session_id: str,
    ) -> ExecutionResult: ...

    def spawn_subagent(
        self, *,
        worktree: Path,
        parent_session_id: str,
        prompt: str,
        timeout_seconds: int = 300,
    ) -> ExecutionResult: ...


class OpenCodeExecutor:
    """Invokes OpenCode as a subprocess. v2's only implementation.

    Assumes `opencode` is on PATH. Uses `opencode run` non-interactive mode.
    The `baseline_sha_provider` lets tests inject a known baseline; real
    callers get a default that reads HEAD.
    """

    def __init__(
        self,
        model: str,
        *,
        opencode_binary: str = "opencode",
        timeout_seconds: int = 900,
        baseline_sha_provider: Optional[Callable[[], str]] = None,
    ):
        self.model = model
        self.opencode_binary = opencode_binary
        self.timeout_seconds = timeout_seconds
        self._baseline_sha_provider = baseline_sha_provider

    def _baseline_sha(self, worktree: Path) -> str:
        if self._baseline_sha_provider is not None:
            return self._baseline_sha_provider()
        return self._current_head(worktree)

    def _current_head(self, worktree: Path) -> str:
        try:
            out = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=str(worktree),
                stderr=subprocess.DEVNULL, timeout=10,
            )
            return out.decode().strip()
        except Exception:
            return ""

    def _files_touched(self, worktree: Path, since_sha: str) -> list[str]:
        try:
            out = subprocess.check_output(
                ["git", "diff", f"{since_sha}..HEAD", "--name-only"],
                cwd=str(worktree), stderr=subprocess.DEVNULL, timeout=10,
            )
            return [l.strip() for l in out.decode().splitlines() if l.strip()]
        except Exception:
            return []

    def _build_prompt(self, story: Any, persona_scaffold: str) -> str:
        files_hint = ", ".join(getattr(story, "files_to_touch", []) or []) or "(inferred from story)"
        return (
            f"{persona_scaffold}\n\n"
            f"═══ STORY ═══\n"
            f"issue_id: {getattr(story, 'issue_id', '?')}\n"
            f"title:    {getattr(story, 'title', '')}\n"
            f"type:     {getattr(story, 'type', '')}\n"
            f"priority: {getattr(story, 'priority', 0)}\n"
            f"expected files_to_touch: {files_hint}\n\n"
            f"═══ BODY ═══\n"
            f"{getattr(story, 'body', '')}\n\n"
            f"═══ INSTRUCTIONS ═══\n"
            f"Do the work described above in the current directory. When done, commit "
            f"your changes with a descriptive message. Run any relevant tests first."
        )

    def run_story(
        self, *,
        worktree: Path,
        story: Any,
        persona_scaffold: str,
        session_id: str,
    ) -> ExecutionResult:
        baseline = self._baseline_sha(worktree)
        prompt = self._build_prompt(story, persona_scaffold)
        t0 = time.time()

        try:
            cp = subprocess.run(
                [
                    self.opencode_binary, "run",
                    "--model", self.model,
                    "--session", session_id,
                    prompt,
                ],
                cwd=str(worktree),
                capture_output=True, text=True,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as e:
            return ExecutionResult(
                success=False,
                error=f"timeout after {self.timeout_seconds}s",
                wall_seconds=round(time.time() - t0, 2),
            )
        except FileNotFoundError:
            return ExecutionResult(
                success=False,
                error=f"opencode binary not found: {self.opencode_binary}",
                wall_seconds=round(time.time() - t0, 2),
            )
        except Exception as e:
            return ExecutionResult(
                success=False, error=f"{type(e).__name__}: {e}",
                wall_seconds=round(time.time() - t0, 2),
            )

        wall = round(time.time() - t0, 2)
        head = self._current_head(worktree)

        if not head or head == baseline:
            return ExecutionResult(
                success=False,
                error="no commit landed (HEAD unchanged from baseline)",
                wall_seconds=wall,
                raw_stdout=(cp.stdout or "")[-2000:],
                raw_stderr=(cp.stderr or "")[-2000:],
            )
        if cp.returncode != 0:
            return ExecutionResult(
                success=False,
                error=f"opencode exit code {cp.returncode}",
                commit_sha=head,
                files_touched=self._files_touched(worktree, baseline),
                wall_seconds=wall,
                raw_stdout=(cp.stdout or "")[-2000:],
                raw_stderr=(cp.stderr or "")[-2000:],
            )

        return ExecutionResult(
            success=True,
            commit_sha=head,
            files_touched=self._files_touched(worktree, baseline),
            learnings=(cp.stdout or "").strip()[-1000:],
            wall_seconds=wall,
            raw_stdout=(cp.stdout or "")[-2000:],
            raw_stderr=(cp.stderr or "")[-2000:],
        )

    def spawn_subagent(
        self, *,
        worktree: Path,
        parent_session_id: str,
        prompt: str,
        timeout_seconds: int = 300,
    ) -> ExecutionResult:
        """Run a subagent (fresh session) for a specialized subtask.
        Returns whatever the subagent said as `learnings`; doesn't require
        a git commit.
        """
        t0 = time.time()
        sub_session = f"{parent_session_id}:sub:{int(time.time())}"
        try:
            cp = subprocess.run(
                [
                    self.opencode_binary, "run",
                    "--model", self.model,
                    "--session", sub_session,
                    prompt,
                ],
                cwd=str(worktree),
                capture_output=True, text=True, timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return ExecutionResult(
                success=False, error=f"subagent timeout after {timeout_seconds}s",
                wall_seconds=round(time.time() - t0, 2),
            )
        except Exception as e:
            return ExecutionResult(
                success=False, error=f"{type(e).__name__}: {e}",
                wall_seconds=round(time.time() - t0, 2),
            )
        return ExecutionResult(
            success=(cp.returncode == 0),
            learnings=(cp.stdout or "").strip()[-2000:],
            wall_seconds=round(time.time() - t0, 2),
            raw_stdout=(cp.stdout or "")[-2000:],
            raw_stderr=(cp.stderr or "")[-2000:],
        )

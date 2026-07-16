"""CodingExecutor Protocol + implementations.

Executors are chosen by preference in the CLI (see `orgos/cli.py::_cmd_start`):
  1. ClaudeCodeExecutor  — if the `claude` CLI is on PATH (uses the user's
                           Claude subscription; no API key visible to orgos)
  2. CopilotCliExecutor  — if the `copilot` CLI is on PATH (uses the user's
                           GitHub Copilot subscription; no API key either)
  3. SpawnCodingExecutor — fallback that uses orgos.spawn + LiteLLM (see
                           orgos/agile/spawn_executor.py) — this is where
                           the OpenAI-URL / DeepSeek-API-key path lives.

Success criterion for any executor: HEAD advanced past the pre-run baseline
inside the given worktree. Executor may return failure with a `.error`
message otherwise.
"""

from __future__ import annotations

import os
import re
import subprocess as _subprocess_real
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Protocol


_ANSI_RE = re.compile(r"\x1B\[[0-9;?]*[A-Za-z]")


def _strip_ansi(s: str) -> str:
    return _ANSI_RE.sub("", s or "")


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


class ClaudeCodeExecutor:
    """Invokes Claude Code as a headless subprocess (`claude -p <prompt>`).

    Assumes the `claude` CLI is on PATH and already authenticated (the user
    logged in once with `claude login`). No API key is passed by orgos —
    the user's Claude subscription handles billing/auth.

    Success = HEAD advanced past the pre-run baseline in the given worktree.
    """

    def __init__(
        self,
        *,
        claude_binary: str = "claude",
        timeout_seconds: int = 900,
        baseline_sha_provider: Optional[Callable[[], str]] = None,
    ):
        self.claude_binary = claude_binary
        self.timeout_seconds = timeout_seconds
        self._baseline_sha_provider = baseline_sha_provider

    def _baseline_sha(self, worktree: Path) -> str:
        if self._baseline_sha_provider is not None:
            return self._baseline_sha_provider()
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(worktree),
            capture_output=True, text=True, timeout=10,
        )
        return (r.stdout or "").strip()

    def _current_head(self, worktree: Path) -> str:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(worktree),
            capture_output=True, text=True, timeout=10,
        )
        return (r.stdout or "").strip()

    def _files_touched(self, worktree: Path, since_sha: str) -> list[str]:
        r = subprocess.run(
            ["git", "diff", f"{since_sha}..HEAD", "--name-only"],
            cwd=str(worktree), capture_output=True, text=True, timeout=10,
        )
        return [l.strip() for l in (r.stdout or "").splitlines() if l.strip()]

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
            f"Do the work described above in the current working directory. "
            f"When done, commit your changes with a descriptive message. "
            f"Run any relevant tests first."
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
                [self.claude_binary, "-p", prompt],
                cwd=str(worktree),
                capture_output=True, text=True,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return ExecutionResult(
                success=False,
                error=f"timeout after {self.timeout_seconds}s",
                wall_seconds=round(time.time() - t0, 2),
            )
        except FileNotFoundError:
            return ExecutionResult(
                success=False,
                error=f"claude binary not found: {self.claude_binary}",
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
                error=f"claude exit code {cp.returncode}",
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
        """Run a subagent (fresh headless Claude) for a specialized subtask.
        Returns whatever Claude said as `learnings`; no git commit required.
        """
        t0 = time.time()
        try:
            cp = subprocess.run(
                [self.claude_binary, "-p", prompt],
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


# ─── GitHub Copilot CLI executor ─────────────────────────────────────────────

_COPILOT_PROMPT_ENV = "ORGOS_COPILOT_PROMPT"


class CopilotCliExecutor:
    """Invokes GitHub Copilot CLI as a headless subprocess (`copilot -p <prompt>`).

    Assumes the `copilot` CLI is on PATH and authenticated (`copilot` then
    `/login`, once). No API token is passed by orgos — auth lives in the CLI.

    Model / policy come from env vars (compatible with the reference JS
    provider you shared):

      COPILOT_COMMAND     Base command. Default 'copilot'.
      COPILOT_MODEL       Passed as `--model`. Optional.
      COPILOT_ALLOW_ALL   '0' to deny shell + write tools. Default '1' —
                          orgos is a coding executor and needs to write
                          files and run tests. Override at your own risk.
      COPILOT_EXTRA_ARGS  Extra space-separated args appended to every call.
      COPILOT_TIMEOUT_MS  Per-call timeout in ms. Default: constructor arg.

    Prompt is passed via the ORGOS_COPILOT_PROMPT env var and referenced on
    the command line — this sidesteps shell-quoting problems for
    multi-line/JSON prompts. On POSIX we still just spawn argv-style since
    Python's `subprocess.run(..., shell=False)` handles argv cleanly; the
    env-var indirection kicks in only if the caller sets COPILOT_USE_ENV=1.
    """

    def __init__(
        self,
        *,
        copilot_binary: Optional[str] = None,
        timeout_seconds: int = 900,
        baseline_sha_provider: Optional[Callable[[], str]] = None,
    ):
        self.copilot_binary = (
            copilot_binary
            or os.environ.get("COPILOT_COMMAND", "copilot").split()[0]
        )
        # Base args baked into COPILOT_COMMAND ("copilot chat" for example).
        raw = (os.environ.get("COPILOT_COMMAND", "copilot") or "copilot").split()
        self._base_args = raw[1:]
        # Honor COPILOT_TIMEOUT_MS if set, else the constructor arg.
        env_timeout_ms = os.environ.get("COPILOT_TIMEOUT_MS")
        if env_timeout_ms and env_timeout_ms.isdigit():
            self.timeout_seconds = max(1, int(env_timeout_ms) // 1000)
        else:
            self.timeout_seconds = timeout_seconds
        self._baseline_sha_provider = baseline_sha_provider

    def _flag_args(self) -> list[str]:
        args: list[str] = []
        model = os.environ.get("COPILOT_MODEL", "").strip()
        if model:
            args += ["--model", model]
        # Coding executor needs shell + write. Default is allow-all; user
        # can opt into safe mode with COPILOT_ALLOW_ALL=0.
        allow = os.environ.get("COPILOT_ALLOW_ALL", "1").strip()
        if allow == "0":
            args += ["--deny-tool", "shell", "--deny-tool", "write"]
        else:
            args += ["--allow-all-tools"]
        extra = os.environ.get("COPILOT_EXTRA_ARGS", "").strip()
        if extra:
            args += extra.split()
        return args

    def _baseline_sha(self, worktree: Path) -> str:
        if self._baseline_sha_provider is not None:
            return self._baseline_sha_provider()
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(worktree),
            capture_output=True, text=True, timeout=10,
        )
        return (r.stdout or "").strip()

    def _current_head(self, worktree: Path) -> str:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(worktree),
            capture_output=True, text=True, timeout=10,
        )
        return (r.stdout or "").strip()

    def _files_touched(self, worktree: Path, since_sha: str) -> list[str]:
        r = subprocess.run(
            ["git", "diff", f"{since_sha}..HEAD", "--name-only"],
            cwd=str(worktree), capture_output=True, text=True, timeout=10,
        )
        return [l.strip() for l in (r.stdout or "").splitlines() if l.strip()]

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
            f"Do the work described above in the current working directory. "
            f"When done, commit your changes with a descriptive message. "
            f"Run any relevant tests first."
        )

    def _spawn_env(self, prompt: str) -> dict:
        env = dict(os.environ)
        env[_COPILOT_PROMPT_ENV] = prompt
        return env

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

        argv = [self.copilot_binary, *self._base_args, "-p", prompt, *self._flag_args()]

        try:
            cp = subprocess.run(
                argv,
                cwd=str(worktree),
                capture_output=True, text=True,
                timeout=self.timeout_seconds,
                env=self._spawn_env(prompt),
            )
        except subprocess.TimeoutExpired:
            return ExecutionResult(
                success=False,
                error=f"timeout after {self.timeout_seconds}s",
                wall_seconds=round(time.time() - t0, 2),
            )
        except FileNotFoundError:
            return ExecutionResult(
                success=False,
                error=(
                    f"copilot binary not found: {self.copilot_binary}. "
                    f"Install `gh extension install github/gh-copilot` or "
                    f"`npm i -g @github/copilot-cli` and run `copilot` + "
                    f"`/login` once."
                ),
                wall_seconds=round(time.time() - t0, 2),
            )
        except Exception as e:
            return ExecutionResult(
                success=False, error=f"{type(e).__name__}: {e}",
                wall_seconds=round(time.time() - t0, 2),
            )

        wall = round(time.time() - t0, 2)
        head = self._current_head(worktree)
        stdout_clean = _strip_ansi(cp.stdout or "")
        stderr_clean = _strip_ansi(cp.stderr or "")

        if not head or head == baseline:
            return ExecutionResult(
                success=False,
                error="no commit landed (HEAD unchanged from baseline)",
                wall_seconds=wall,
                raw_stdout=stdout_clean[-2000:],
                raw_stderr=stderr_clean[-2000:],
            )
        if cp.returncode != 0:
            return ExecutionResult(
                success=False,
                error=f"copilot exit code {cp.returncode}",
                commit_sha=head,
                files_touched=self._files_touched(worktree, baseline),
                wall_seconds=wall,
                raw_stdout=stdout_clean[-2000:],
                raw_stderr=stderr_clean[-2000:],
            )

        return ExecutionResult(
            success=True,
            commit_sha=head,
            files_touched=self._files_touched(worktree, baseline),
            learnings=stdout_clean.strip()[-1000:],
            wall_seconds=wall,
            raw_stdout=stdout_clean[-2000:],
            raw_stderr=stderr_clean[-2000:],
        )

    def spawn_subagent(
        self, *,
        worktree: Path,
        parent_session_id: str,
        prompt: str,
        timeout_seconds: int = 300,
    ) -> ExecutionResult:
        """Fresh headless copilot for a subtask. No git commit required."""
        t0 = time.time()
        argv = [self.copilot_binary, *self._base_args, "-p", prompt, *self._flag_args()]
        try:
            cp = subprocess.run(
                argv,
                cwd=str(worktree),
                capture_output=True, text=True, timeout=timeout_seconds,
                env=self._spawn_env(prompt),
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
            learnings=_strip_ansi(cp.stdout or "").strip()[-2000:],
            wall_seconds=round(time.time() - t0, 2),
            raw_stdout=_strip_ansi(cp.stdout or "")[-2000:],
            raw_stderr=_strip_ansi(cp.stderr or "")[-2000:],
        )

"""SpawnCodingExecutor — CodingExecutor implementation using orgos.spawn.

Alternative to OpenCodeExecutor. Uses the existing CrewAI-based worker roles
(architect_role / test_role / devsecops_role) with a BashTool scoped to the
agent's worktree. Same success criterion as OpenCode: HEAD must advance.

Why: OpenCodeExecutor adds an external binary dependency and opaque failure
modes. The spawn pipeline is already proven (v1 waterfall built a full Flask
app end-to-end with 150/150 tests) and its events flow through orgos's own
EventEmitter, so debugging goes through live.jsonl instead of opencode's
session logs.

Trade-off: BashTool is less ergonomic for the LLM than opencode's Read/Edit/
Grep tools, but it can *do* the same things (via cat/heredoc/sed/grep). For
bite-sized stories (single endpoint, single function) it is sufficient.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable, Optional

from orgos.agile.coding_executor import ExecutionResult
from orgos.spawn import TaskBrief, spawn
from orgos.subagents import architect_role, devsecops_role, test_role
from orgos.tools.bash import BashTool


_ARCH_BRIEF = """You are the Architect. Build the story below.

STORY
  issue_id: {issue_id}
  title:    {title}
  type:     {type}
  files_to_touch (hint): {files_hint}

BODY
{body}

WORKTREE: {worktree}
UNIX shell available. Use `cat`, heredocs, `pytest`, `git`.

STEPS
1. Write the code the story asks for. If tests are implied, add them.
2. Run any tests you added: `pytest <path> -v` (keep going even if warnings).
3. Commit:
     git add -A
     git -c user.name=orgos-arch -c user.email=arch@orgos.local commit -m "{type}: {title}"
4. `git rev-parse HEAD`
5. Emit ONLY this envelope JSON:

{{
  "role": "architect",
  "status": "completed",
  "summary": "<what you did>",
  "payload": {{
    "commit_sha": "<sha>",
    "files_touched": ["<paths>"],
    "test_command": "<pytest cmd or empty>",
    "test_output": "<tail 500 chars>",
    "test_passed": true
  }}
}}

RULES
  - First bash call is productive (heredoc), not exploration.
  - Do not modify governance files (orgos/spawn/**).
  - If you cannot complete the story in one attempt, still commit whatever
    progress you made so the next agent has state to build on.
"""

_TEST_BRIEF = """You are Test. Add or improve tests for the story below.

STORY
  issue_id: {issue_id}
  title:    {title}
  files_to_touch (hint): {files_hint}

BODY
{body}

WORKTREE: {worktree}

STEPS
1. Read the existing code that this story tests: `cat <path>`.
2. Write test file(s) via heredoc. Run them: `pytest <path> -v`.
3. Commit:
     git add -A
     git -c user.name=orgos-test -c user.email=test@orgos.local commit -m "test: {title}"
4. `git rev-parse HEAD`
5. Emit envelope:

{{
  "role": "test",
  "status": "completed",
  "summary": "<what you added>",
  "payload": {{
    "commit_sha": "<sha>",
    "files_touched": ["<paths>"],
    "test_command": "<cmd>",
    "test_output": "<tail>",
    "test_passed": true
  }}
}}
"""

_SEC_BRIEF = """You are DevSecOps. Add security guards / validation for the story below.

STORY
  issue_id: {issue_id}
  title:    {title}
  files_to_touch (hint): {files_hint}

BODY
{body}

WORKTREE: {worktree}

STEPS
1. Read the target code.
2. Add validation / auth / secret-handling as the story describes.
3. Commit:
     git add -A
     git -c user.name=orgos-sec -c user.email=sec@orgos.local commit -m "sec: {title}"
4. `git rev-parse HEAD`
5. Emit envelope with role=devsecops.
"""


_BRIEF_BY_ROLE = {
    "architect": _ARCH_BRIEF,
    "test":      _TEST_BRIEF,
    "devsecops": _SEC_BRIEF,
}

def _factory_for(role_name: str):
    """Late-binding lookup so tests can monkeypatch role factories on this module."""
    import orgos.agile.spawn_executor as _self  # local ref to catch patched attrs
    return {
        "architect": _self.architect_role,
        "test":      _self.test_role,
        "devsecops": _self.devsecops_role,
    }[role_name]


class SpawnCodingExecutor:
    """CodingExecutor that uses orgos.spawn + BashTool. No external binary.

    Selects the CrewAI role by the `session_id` passed to `run_story`
    (which AsyncAgent sets to its role name).
    """

    def __init__(
        self,
        model: str,
        *,
        run_budget_tokens: int = 1_200_000,
        baseline_sha_provider: Optional[Callable[[], str]] = None,
    ):
        self.model = model
        self.run_budget_tokens = run_budget_tokens
        self._baseline_sha_provider = baseline_sha_provider

    def _baseline_sha(self, worktree: Path) -> str:
        if self._baseline_sha_provider is not None:
            return self._baseline_sha_provider()
        import subprocess as _sp
        r = _sp.run(
            ["git", "rev-parse", "HEAD"], cwd=str(worktree),
            capture_output=True, text=True, timeout=10,
        )
        return (r.stdout or "").strip()

    def _current_head(self, worktree: Path) -> str:
        import subprocess as _sp
        r = _sp.run(
            ["git", "rev-parse", "HEAD"], cwd=str(worktree),
            capture_output=True, text=True, timeout=10,
        )
        return (r.stdout or "").strip()

    def _files_touched(self, worktree: Path, since_sha: str) -> list[str]:
        import subprocess as _sp
        r = _sp.run(
            ["git", "diff", f"{since_sha}..HEAD", "--name-only"],
            cwd=str(worktree), capture_output=True, text=True, timeout=10,
        )
        return [l.strip() for l in (r.stdout or "").splitlines() if l.strip()]

    def run_story(
        self, *,
        worktree: Path,
        story: Any,
        persona_scaffold: str,
        session_id: str,
    ) -> ExecutionResult:
        role_name = session_id if session_id in _BRIEF_BY_ROLE else "architect"
        template = _BRIEF_BY_ROLE[role_name]
        factory = _factory_for(role_name)

        files_hint = ", ".join(getattr(story, "files_to_touch", []) or []) or "(inferred)"
        prompt = template.format(
            issue_id=getattr(story, "issue_id", "?"),
            title=getattr(story, "title", ""),
            type=getattr(story, "type", ""),
            body=(getattr(story, "body", "") or "(no body)"),
            worktree=str(worktree),
            files_hint=files_hint,
        )

        role = factory(
            model=self.model,
            extra_tools=[BashTool(default_working_dir=str(worktree))],
        )
        role.mcp_servers = []  # no wiki MCP inside the coding path

        brief = TaskBrief(
            objective=prompt,
            expected_output="Envelope JSON with commit_sha.",
            success_criteria=["A commit was created."],
        )

        baseline = self._baseline_sha(worktree)
        t0 = time.time()

        try:
            result = spawn(role, brief, run_budget_tokens=self.run_budget_tokens)
        except Exception as e:
            return ExecutionResult(
                success=False,
                error=f"spawn_exception:{type(e).__name__}:{e}"[:400],
                wall_seconds=round(time.time() - t0, 2),
            )

        wall = round(time.time() - t0, 2)
        head = self._current_head(worktree)
        tu = result.token_usage or {}
        tokens_in = int(tu.get("prompt_tokens", 0) or 0)
        tokens_out = int(tu.get("completion_tokens", 0) or 0)

        # Try to extract the envelope for the learnings field.
        summary_text = ""
        try:
            for to in result.tasks_output:
                raw = getattr(to, "raw", "") or ""
                # find last {...} block ending near end of text
                start = raw.find("{")
                if start >= 0:
                    tail = raw[start:]
                    for end in range(len(tail), 0, -1):
                        try:
                            data = json.loads(tail[:end])
                            if isinstance(data, dict):
                                summary_text = str(data.get("summary", ""))[:1000]
                                break
                        except json.JSONDecodeError:
                            continue
                if summary_text:
                    break
        except Exception:
            pass

        if not head or head == baseline:
            return ExecutionResult(
                success=False,
                error="no commit landed (HEAD unchanged from baseline)",
                wall_seconds=wall,
                tokens_input=tokens_in,
                tokens_output=tokens_out,
                learnings=summary_text,
            )

        return ExecutionResult(
            success=True,
            commit_sha=head,
            files_touched=self._files_touched(worktree, baseline),
            learnings=summary_text,
            tokens_input=tokens_in,
            tokens_output=tokens_out,
            wall_seconds=wall,
        )

    def spawn_subagent(
        self, *,
        worktree: Path,
        parent_session_id: str,
        prompt: str,
        timeout_seconds: int = 300,
    ) -> ExecutionResult:
        """Delegated subtask via a fresh architect spawn. No commit required."""
        role = architect_role(
            model=self.model,
            extra_tools=[BashTool(default_working_dir=str(worktree))],
        )
        role.mcp_servers = []
        brief = TaskBrief(
            objective=prompt,
            expected_output="Any output.",
            success_criteria=[],
        )
        t0 = time.time()
        try:
            result = spawn(role, brief, run_budget_tokens=300_000)
        except Exception as e:
            return ExecutionResult(
                success=False,
                error=f"subagent_exception:{type(e).__name__}:{e}"[:400],
                wall_seconds=round(time.time() - t0, 2),
            )
        return ExecutionResult(
            success=True,
            learnings=(result.tasks_output[0].raw if result.tasks_output else "")[-2000:],
            wall_seconds=round(time.time() - t0, 2),
        )

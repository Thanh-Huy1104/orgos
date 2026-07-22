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
from agentkit.governance import TaskBrief, spawn
from orgos.subagents import architect_role, devsecops_role, test_role
from orgos.tools.bash import BashTool


_ARCH_BRIEF = """You are the Architect. Ship the story below in ONE commit.

STORY {issue_id}  (type={type})
  title: {title}
  files hint: {files_hint}

{body}

WORKTREE: {worktree}    (UNIX shell + cat + heredocs + pytest + git)

═══ CRITICAL: THE COMMIT IS THE ONLY THING THAT COUNTS ═══
Success = `git rev-parse HEAD` advances past its baseline.
The envelope JSON at the end is optional bookkeeping — SKIP IT if you're
running low on iterations. The commit is not optional.

═══ ORDER (do these in this order, do not skip commit) ═══
1. Write code with heredoc (`cat > path <<'EOF' … EOF`). First bash call is
   productive, not exploration.
2. If this story is type=architecture, append to wiki/DECISIONS.md the
   EXACT format below. Use `field: value` (NOT `**field:**` markdown-bold
   — the DoD gate's regex does not match bold form):

       ## <one-line decision summary>
       author: architect-agent
       timestamp: <ISO-8601 UTC>
       source: {issue_id}

       <2-4 sentences>

   Without this, PO's DoD gate blocks the story on acceptance. (orgos
   also auto-writes a stub if you skip this step, but yours will have
   better rationale.)
3. **COMMIT NOW** — even before running tests:
       git add -A
       git -c user.name=orgos-arch -c user.email=arch@orgos.local commit -m "{type}: {title}"
4. Then run tests: `pytest <path> -v` (informational; not required to pass).
5. (Optional) Emit envelope JSON:
   {{"role":"architect","status":"completed","summary":"<what>","payload":{{"commit_sha":"<sha>","files_touched":[...]}}}}

═══ RULES ═══
  - Committed partial progress > uncommitted "clean" code. ALWAYS commit
    whatever you have before your turn ends.
  - Do not modify governance files (orgos/spawn/**).
  - Only touch wiki/DECISIONS.md if this story is type=architecture.
"""

_TEST_BRIEF = """You are Test. Ship tests for the story below in ONE commit.

STORY {issue_id}
  title: {title}
  files hint: {files_hint}

{body}

WORKTREE: {worktree}

═══ CRITICAL: THE COMMIT IS THE ONLY THING THAT COUNTS ═══
Success = HEAD advances. Envelope JSON is optional.

═══ ORDER ═══
1. Read the code under test: `cat <path>`.
2. Write test file(s) with heredoc.
3. **COMMIT NOW**:
       git add -A
       git -c user.name=orgos-test -c user.email=test@orgos.local commit -m "test: {title}"
4. Then run tests (informational): `pytest <path> -v`.
5. (Optional) Envelope: {{"role":"test","status":"completed","payload":{{"commit_sha":"<sha>"}}}}
"""

_SEC_BRIEF = """You are DevSecOps. Ship security guards for the story below in ONE commit.

STORY {issue_id}
  title: {title}
  files hint: {files_hint}

{body}

WORKTREE: {worktree}

═══ CRITICAL: THE COMMIT IS THE ONLY THING THAT COUNTS ═══
Success = HEAD advances. Envelope JSON is optional.

═══ ORDER ═══
1. Read target code.
2. Add validation / auth / secret handling.
3. **COMMIT NOW**:
       git add -A
       git -c user.name=orgos-sec -c user.email=sec@orgos.local commit -m "sec: {title}"
4. (Optional) Envelope: {{"role":"devsecops","status":"completed","payload":{{"commit_sha":"<sha>"}}}}
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

    def _has_uncommitted_changes(self, worktree: Path) -> bool:
        """True if `git status --porcelain` reports any tracked or untracked change."""
        import subprocess as _sp
        r = _sp.run(
            ["git", "status", "--porcelain"], cwd=str(worktree),
            capture_output=True, text=True, timeout=10,
        )
        return bool((r.stdout or "").strip())

    def _wip_commit(self, worktree: Path, *, message: str) -> str:
        """Stage everything + commit with a WIP message. Returns new HEAD sha
        or '' on failure. Used as the auto-commit fallback when the LLM
        wrote files but skipped `git commit`.
        """
        import subprocess as _sp
        try:
            _sp.run(["git", "add", "-A"], cwd=str(worktree),
                    check=True, capture_output=True, timeout=15)
            r = _sp.run(
                ["git", "-c", "user.name=orgos-wip",
                 "-c", "user.email=wip@orgos.local",
                 "commit", "-m", message],
                cwd=str(worktree), capture_output=True, text=True, timeout=15,
            )
            if r.returncode != 0:
                return ""
            head = _sp.run(
                ["git", "rev-parse", "HEAD"], cwd=str(worktree),
                capture_output=True, text=True, timeout=10,
            )
            return (head.stdout or "").strip()
        except (_sp.SubprocessError, OSError):
            return ""

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
        # Bump reasoning cap for coding work. Default (20) was too tight in
        # the 4h at-scale run — "write code + tests + pytest + git commit
        # + emit envelope" often needs 25-35 turns on complex stories, and
        # hitting the cap = LLM stops without committing (was 29/39 no_commits
        # in Run 4). Bump to 40 for headroom.
        role.max_iter = 40

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
            # LLM didn't run `git commit`. Check if it at least wrote files —
            # if so, auto-commit them with a WIP prefix and treat as success.
            # This turns "LLM forgot the commit step" from a total loss into
            # a partial delivery. Zero extra LLM cost.
            if self._has_uncommitted_changes(worktree):
                wip_sha = self._wip_commit(
                    worktree,
                    message=f"WIP: {getattr(story, 'title', 'story')} [{getattr(story, 'issue_id', '')}]",
                )
                if wip_sha and wip_sha != baseline:
                    return ExecutionResult(
                        success=True,
                        commit_sha=wip_sha,
                        files_touched=self._files_touched(worktree, baseline),
                        learnings=(summary_text + " [auto-committed: LLM wrote code but did not run git commit]")[:1000],
                        tokens_input=tokens_in,
                        tokens_output=tokens_out,
                        wall_seconds=wall,
                    )
            return ExecutionResult(
                success=False,
                error="no commit landed (HEAD unchanged from baseline; no uncommitted changes either)",
                wall_seconds=wall,
                tokens_input=tokens_in,
                tokens_output=tokens_out,
                learnings=summary_text,
            )

        # DoD auto-write for architecture stories. If the story is
        # type=architecture and its committed diff doesn't already record a
        # compliant wiki/DECISIONS.md entry citing this issue_id, orgos writes
        # the stub itself and amends the commit. Removes LLM unreliability
        # from the DoD path — the executor guarantees the wiki entry lands.
        if getattr(story, "type", "") == "architecture":
            head_after_dod = self._ensure_arch_wiki_entry(
                worktree, story, head, summary_text,
            )
            if head_after_dod:
                head = head_after_dod

        return ExecutionResult(
            success=True,
            commit_sha=head,
            files_touched=self._files_touched(worktree, baseline),
            learnings=summary_text,
            tokens_input=tokens_in,
            tokens_output=tokens_out,
            wall_seconds=wall,
        )

    def _ensure_arch_wiki_entry(
        self, worktree: Path, story: Any, current_head: str, summary_text: str,
    ) -> str:
        """Ensure wiki/DECISIONS.md has a compliant entry citing story.issue_id.
        If missing, write a stub with the three mandatory fields and amend
        (or add) a commit. Returns the new HEAD sha, or '' on failure.
        Never raises — a failure here degrades gracefully to "PO will block
        it" (the pre-fix behavior).
        """
        try:
            from orgos.mcps.wiki_mcp import decisions_cite_source
        except Exception:
            return ""

        issue_id = getattr(story, "issue_id", "").strip()
        if not issue_id:
            return ""

        # Wiki lives at repo/wiki/DECISIONS.md (agents were told to touch it
        # in the worktree). Check the CURRENT state of the file in the
        # worktree — after the commit.
        decisions_path = worktree / "wiki" / "DECISIONS.md"
        existing = ""
        if decisions_path.exists():
            try:
                existing = decisions_path.read_text(encoding="utf-8")
            except Exception:
                existing = ""

        if existing and decisions_cite_source(existing, issue_id):
            return ""  # already compliant, nothing to do

        # Write a stub entry. Use the story's title as the summary and the
        # LLM's returned summary (if any) as the rationale.
        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        title = str(getattr(story, "title", "architectural decision")).strip()
        rationale = (summary_text or
                     "Auto-recorded by orgos DoD-guard: LLM committed the "
                     "architecture story but did not annotate the decision. "
                     "This stub satisfies the three-field DoD gate; a human "
                     "or a later replan should expand it.")[:600]

        # Use plain "field: value" block form — matches wiki_mcp's regex
        # (`**source:**` markdown-bold syntax is NOT recognized by
        # decisions_cite_source, which is one reason the LLM's own attempts
        # often fail the DoD gate).
        entry = (
            f"\n## {title}\n"
            f"author: architect-agent\n"
            f"timestamp: {ts}\n"
            f"source: {issue_id}\n\n"
            f"{rationale}\n"
        )

        try:
            decisions_path.parent.mkdir(parents=True, exist_ok=True)
            with decisions_path.open("a", encoding="utf-8") as f:
                f.write(entry)
            import subprocess as _sp
            _sp.run(
                ["git", "add", "wiki/DECISIONS.md"], cwd=str(worktree),
                check=True, capture_output=True, timeout=10,
            )
            r = _sp.run(
                ["git", "-c", "user.name=orgos-dod",
                 "-c", "user.email=dod@orgos.local",
                 "commit", "-m", f"docs(dod): auto-record decision for {issue_id}"],
                cwd=str(worktree), capture_output=True, text=True, timeout=10,
            )
            if r.returncode != 0:
                return ""
            head = _sp.run(
                ["git", "rev-parse", "HEAD"], cwd=str(worktree),
                capture_output=True, text=True, timeout=10,
            )
            return (head.stdout or "").strip()
        except Exception:
            return ""

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

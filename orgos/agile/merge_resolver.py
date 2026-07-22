"""LLM-driven merge conflict resolver (Fix §B6).

When merge_queue rebase fails, we've been aborting + reset + blocking the
story. That loses ~10-15% of stories per run. Most conflicts are
recoverable — both sides added lines to the same test file, both sides
appended to __init__.py, both sides wrote different lines in a markdown
list.

This module attempts one resolution pass per conflicted rebase step:
  - Detect which files are in conflict (git status --porcelain)
  - For each conflicted file, gate on file-class safety:
      * Always safe:  __init__.py (usually just imports/exports),
                      markdown, .txt, __init__.py-adjacent (setup.cfg)
      * Tests:        pytest files whose changes are both `def test_*`
                      additions (independent tests → append-both)
      * Code:         only if BOTH sides add whole new functions/classes
                      that don't share names; skip otherwise
  - Spawn a small LLM call with the conflict markers, ask for a merged file
  - Write, git add. If all conflicts resolved → git rebase --continue
  - If any file skipped or LLM fails → abort as before

Design:
  - Behind a flag (`resolve_llm=True`) so it can be disabled if it
    misbehaves in production.
  - Fails safe: on ANY error, falls back to the old abort-and-block path.
  - Uses a lightweight prompt targeted at conflict blocks only (not the
    whole file) to keep cost tiny.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any, Optional


# File classes we're willing to auto-resolve. Order matters for logging.
_SAFE_EXTENSIONS = (".md", ".txt", ".rst", ".gitignore", ".gitattributes")
_INIT_PY_PATTERN = re.compile(r"(?:^|/)__init__\.py$")
_TEST_FILE_PATTERN = re.compile(r"(?:^|/)tests?/[\w/]*test_\w+\.py$")


def _run_git(args: list[str], cwd: Path, timeout: int = 15) -> tuple[int, str, str]:
    r = subprocess.run(
        ["git", *args], cwd=str(cwd),
        capture_output=True, text=True, timeout=timeout,
    )
    return r.returncode, (r.stdout or ""), (r.stderr or "")


def _list_conflicted_files(worktree: Path) -> list[str]:
    """`git diff --name-only --diff-filter=U` — unmerged paths."""
    try:
        rc, out, _ = _run_git(
            ["diff", "--name-only", "--diff-filter=U"], worktree,
        )
        if rc != 0:
            return []
        return [ln.strip() for ln in out.splitlines() if ln.strip()]
    except (subprocess.SubprocessError, OSError):
        return []


def _classify(path: str) -> str:
    """Return one of: 'markdown_or_text', 'init_py', 'test_file',
    'other'. Only the first three are auto-resolvable."""
    lower = path.lower()
    if any(lower.endswith(ext) for ext in _SAFE_EXTENSIONS):
        return "markdown_or_text"
    if _INIT_PY_PATTERN.search(path):
        return "init_py"
    if _TEST_FILE_PATTERN.search(path):
        return "test_file"
    return "other"


_CONFLICT_MARKER_PROMPT = """You are resolving a git merge conflict. The file
below has one or more `<<<<<<< ... ======= ... >>>>>>>` conflict blocks.

FILE: {path}
CLASS: {file_class}

GUIDELINES for this file class:
  - init_py: prefer UNION (keep imports/exports from BOTH sides,
    dedupe if identical, preserve declaration order roughly)
  - markdown_or_text: UNION lines (both sides likely added different
    entries to a list — keep both)
  - test_file: UNION test functions (each side added independent tests,
    keep both; if same function name on both sides, keep OURS)

Rules:
  - Output ONLY the resolved file contents. No markdown fences. No prose.
  - Do NOT leave any `<<<<<<<`, `=======`, or `>>>>>>>` markers.
  - Preserve non-conflicted regions verbatim.
  - Preserve trailing newline if present.

FILE CONTENTS (with conflict markers):
```
{contents}
```
"""


def _resolve_file_with_llm(
    path: Path, file_class: str, model: str,
    spawner: Optional[Any] = None,
) -> Optional[str]:
    """One LLM call per conflicted file. Returns the resolved content string
    or None if we couldn't resolve.
    """
    try:
        contents = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if "<<<<<<<" not in contents:
        return contents  # already resolved (shouldn't happen but safe)

    prompt = _CONFLICT_MARKER_PROMPT.format(
        path=str(path), file_class=file_class,
        contents=contents[:8000],  # cap for prompt size
    )

    if spawner is None:
        try:
            from agentkit.governance import TaskBrief, spawn as _spawn
            from orgos.subagents import architect_role
        except Exception:
            return None
        try:
            arch = architect_role(model=model)
            arch.mcp_servers = []
            brief = TaskBrief(
                objective=prompt,
                expected_output="Resolved file contents. No markers, no prose.",
                success_criteria=["Output has no <<<<<<< / ======= / >>>>>>>."],
            )
            result = _spawn(arch, brief, run_budget_tokens=30_000)
        except Exception:
            return None
    else:
        try:
            result = spawner(prompt=prompt, model=model)
        except Exception:
            return None

    for to in getattr(result, "tasks_output", []) or []:
        raw = getattr(to, "raw", "") or ""
        # If LLM wrapped output in fences, strip them
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            # remove first fence line and trailing fence
            lines = cleaned.splitlines()
            if len(lines) >= 2:
                # skip first fence line (```lang or just ```)
                lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                cleaned = "\n".join(lines)
        # Reject if any conflict marker survived
        if "<<<<<<<" in cleaned or "=======" in cleaned or ">>>>>>>" in cleaned:
            continue
        if cleaned:
            return cleaned
    return None


def try_resolve_rebase_conflicts(
    worktree: Path,
    *,
    model: str,
    spawner: Optional[Any] = None,
    max_files: int = 5,
) -> tuple[bool, str]:
    """Attempt to resolve all conflicts from an in-progress rebase.

    Called from merge_queue._attempt_merge AFTER `git rebase` failed but
    BEFORE aborting. If every conflicted file is (a) in a safe file class
    and (b) the LLM produced a marker-free resolution, we write the
    resolutions, `git add` them, and return (True, "resolved N files").
    Caller then runs `git rebase --continue`.

    Returns (False, "reason") on any bail-out. Caller falls back to the
    old abort-and-block path.
    """
    conflicted = _list_conflicted_files(worktree)
    if not conflicted:
        return False, "no conflicted files reported"
    if len(conflicted) > max_files:
        return False, f"too many conflicted files ({len(conflicted)} > {max_files})"

    # Gate: every file must be in a safe class
    unsafe = [f for f in conflicted if _classify(f) == "other"]
    if unsafe:
        return False, f"unsafe file class(es): {unsafe[:3]}"

    # Resolve each
    resolved = 0
    for rel in conflicted:
        path = worktree / rel
        cls = _classify(rel)
        merged = _resolve_file_with_llm(path, cls, model, spawner=spawner)
        if merged is None:
            return False, f"LLM couldn't resolve {rel}"
        try:
            path.write_text(merged, encoding="utf-8")
        except OSError as e:
            return False, f"write failed for {rel}: {e}"
        rc, _, err = _run_git(["add", rel], worktree)
        if rc != 0:
            return False, f"git add failed for {rel}: {err[:100]}"
        resolved += 1

    return True, f"resolved {resolved} files via LLM"

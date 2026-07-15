"""Deterministic quality checks — no LLM required.

Reads the actual git diff and test output from a sprint worktree
and scores mechanical quality criteria. Combined with the LLM
evaluator in evaluator.py to produce a full QualityReport.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

DIFF_LINE_CAP = 400
SECRET_PATTERNS = [
    r'sk-[a-zA-Z0-9]{20,}',
    r'ghp_[a-zA-Z0-9]{20,}',
    r'password\s*=\s*[\'"]\S+[\'"]',
    r'secret\s*=\s*[\'"]\S+[\'"]',
    r'token\s*=\s*[\'"]\S+[\'"]',
    r'-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----',
]


def _run_git_diff(worktree: Path) -> str:
    result = subprocess.run(
        ["git", "diff", "HEAD~1"],
        cwd=worktree, capture_output=True, text=True,
    )
    return (result.stdout or "") + (result.stderr or "")


def _run_git_diff_stat(worktree: Path) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "HEAD~1", "--name-only"],
        cwd=worktree, capture_output=True, text=True,
    )
    return [f.strip() for f in (result.stdout or "").splitlines() if f.strip()]


def check_diff_size(diff: str) -> tuple[bool, str]:
    lines = sum(1 for l in diff.splitlines() if l.startswith(("+", "-")) and not l.startswith(("+++", "---")))
    ok = lines <= DIFF_LINE_CAP
    return ok, f"diff_lines={lines}" if ok else f"diff_lines={lines} > {DIFF_LINE_CAP}"


def check_files_in_scope(touched_files: list[str], allowlist: list[str] | None = None) -> tuple[bool, str]:
    if not allowlist:
        return True, "no allowlist, all files accepted"
    allowed = set(allowlist)
    touched = set(touched_files)
    extras = touched - allowed
    return not extras, (f"file(s) outside scope: {sorted(extras)}" if extras else "all files in scope")


def check_secrets(diff: str) -> tuple[bool, str]:
    found = []
    for pat in SECRET_PATTERNS:
        matches = re.findall(pat, diff, re.IGNORECASE)
        found.extend(matches)
    return not found, (f"secret(s) found: {found[:3]}" if found else "no secrets detected")


def check_commit_valid(worktree: Path) -> tuple[bool, str]:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=worktree, capture_output=True, text=True,
    )
    sha = (result.stdout or "").strip()
    ok = bool(sha) and len(sha) >= 7
    return ok, f"sha={sha[:12]}" if ok else "no valid commit SHA"


def check_tests_passed(test_output: str) -> tuple[bool, str]:
    if not test_output:
        return True, "no test output provided"
    if "FAILED" in test_output or "ERROR" in test_output:
        return False, "tests show failures"
    if "exit code: 0" in test_output.lower() or "passed" in test_output.lower():
        return True, "tests passed"
    return True, "test output unclear"


def evaluate(worktree: Path, allowlist: list[str] | None = None,
             test_output: str = "") -> dict:
    if not worktree.exists() or not (worktree / ".git").exists():
        return {
            "score": 0.0,
            "criteria": {
                "diff_size": {"passed": False, "reason": "worktree not found"},
                "files_in_scope": {"passed": False, "reason": "worktree not found"},
                "secrets": {"passed": False, "reason": "worktree not found"},
                "commit_valid": {"passed": False, "reason": "worktree not found"},
                "tests_passed": {"passed": False, "reason": "worktree not found"},
            },
        }

    diff = _run_git_diff(worktree)
    touched = _run_git_diff_stat(worktree)

    results = {}
    for name, fn in [
        ("diff_size", lambda: check_diff_size(diff)),
        ("files_in_scope", lambda: check_files_in_scope(touched, allowlist)),
        ("secrets", lambda: check_secrets(diff)),
        ("commit_valid", lambda: check_commit_valid(worktree)),
        ("tests_passed", lambda: check_tests_passed(test_output)),
    ]:
        passed, reason = fn()
        results[name] = {"passed": passed, "reason": reason}

    score = sum(1 for r in results.values() if r["passed"]) / max(len(results), 1)
    return {"score": round(score, 3), "criteria": results}

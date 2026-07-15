"""Benchmark data model + runners for team-vs-solo comparison."""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from orgos.agile.pricing import cost_usd


@dataclass
class BenchmarkRun:
    issue_id: str
    approach: str  # "team" | "solo"
    model: str
    started_at: str
    wall_seconds: float
    tokens_input: int
    tokens_output: int
    tokens_total: int
    cost_usd: float
    commit_produced: bool
    commit_sha: str
    files_changed: int
    loc_added: int
    loc_removed: int
    tests_run: int
    tests_passed: int
    tests_failed: int
    quality_ac: int | None
    quality_code: int | None
    quality_tests: int | None
    quality_summary: str
    diff_text: str
    envelope_trail: list[dict] = field(default_factory=list)
    raw_output: str = ""
    error: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)


def diff_stats(worktree: Path, base_ref: str = "HEAD~1") -> tuple[int, int, int, str]:
    """Return (files, added, removed, full_diff_text)."""
    try:
        numstat = subprocess.run(
            ["git", "diff", f"{base_ref}..HEAD", "--numstat"],
            cwd=str(worktree), capture_output=True, text=True, timeout=30,
        )
        files = 0
        added = 0
        removed = 0
        for line in numstat.stdout.strip().splitlines():
            parts = line.split()
            if len(parts) < 3:
                continue
            try:
                a = int(parts[0]) if parts[0].isdigit() else 0
                r = int(parts[1]) if parts[1].isdigit() else 0
                added += a
                removed += r
                files += 1
            except ValueError:
                continue
        full = subprocess.run(
            ["git", "diff", f"{base_ref}..HEAD"],
            cwd=str(worktree), capture_output=True, text=True, timeout=30,
        ).stdout
        return files, added, removed, full
    except Exception:
        return 0, 0, 0, ""


def pytest_stats(pytest_output: str) -> tuple[int, int, int]:
    """Parse a pytest tail line for (run, passed, failed)."""
    import re
    m = re.search(r"(\d+) passed", pytest_output or "")
    passed = int(m.group(1)) if m else 0
    m = re.search(r"(\d+) failed", pytest_output or "")
    failed = int(m.group(1)) if m else 0
    return passed + failed, passed, failed


def run_team(
    repo_path: Path,
    issue: dict,
    *,
    model: str,
    run_budget_tokens: int = 2_500_000,
) -> tuple[Any, "BenchmarkRun"]:
    """Wrap run_pull_sprint into a BenchmarkRun with the same schema as solo."""
    import time
    from orgos.agile.sprint import run_pull_sprint

    t0 = time.time()
    err = ""
    sprint = None
    try:
        sprint = run_pull_sprint(
            repo_path, issue, model=model, mock_pr=True,
            run_budget_tokens=run_budget_tokens,
        )
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
    wall = time.time() - t0

    tokens_in = getattr(sprint, "total_tokens_input", 0) if sprint else 0
    tokens_out = getattr(sprint, "total_tokens_output", 0) if sprint else 0

    envelope_trail = []
    quality_ac = quality_code = quality_tests = None
    quality_summary = ""
    commit_sha = ""
    if sprint:
        for role_name, env in sprint.envelopes.items():
            if isinstance(env, dict):
                envelope_trail.append({"role": role_name, **env})
        arch = sprint.envelopes.get("architect", {}) or {}
        if isinstance(arch, dict):
            commit_sha = (arch.get("payload", {}) or {}).get("commit_sha", "") or ""
        q = sprint.envelopes.get("quality", {}) or {}
        scores = q.get("llm_scores", {}) if isinstance(q, dict) else {}
        quality_ac = scores.get("ac_compliance")
        quality_code = scores.get("code_quality")
        quality_tests = scores.get("test_relevance")
        quality_summary = q.get("llm_summary", "") if isinstance(q, dict) else ""

    baseline_sha = getattr(sprint, "baseline_sha", "") if sprint else ""
    files = added = removed = 0
    diff_text = ""
    commit_produced = False
    if sprint and baseline_sha:
        files, added, removed, diff_text = diff_stats(sprint.worktree_path, baseline_sha)
        import subprocess
        current_head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(sprint.worktree_path), capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        commit_produced = bool(current_head) and current_head != baseline_sha

    test_output = ""
    if sprint:
        arch = sprint.envelopes.get("architect", {}) or {}
        if isinstance(arch, dict):
            test_output = (arch.get("payload", {}) or {}).get("test_output", "") or ""
    tests_run, tests_passed, tests_failed = pytest_stats(test_output)

    run = BenchmarkRun(
        issue_id=issue.get("issue_id", "?"),
        approach="team",
        model=model,
        started_at=sprint.started_at if sprint else "",
        wall_seconds=round(wall, 2),
        tokens_input=tokens_in,
        tokens_output=tokens_out,
        tokens_total=tokens_in + tokens_out,
        cost_usd=round(cost_usd(model, tokens_in, tokens_out), 6),
        commit_produced=commit_produced,
        commit_sha=commit_sha,
        files_changed=files,
        loc_added=added,
        loc_removed=removed,
        tests_run=tests_run,
        tests_passed=tests_passed,
        tests_failed=tests_failed,
        quality_ac=quality_ac,
        quality_code=quality_code,
        quality_tests=quality_tests,
        quality_summary=quality_summary,
        diff_text=diff_text,
        envelope_trail=envelope_trail,
        raw_output="",
        error=err,
    )
    return sprint, run

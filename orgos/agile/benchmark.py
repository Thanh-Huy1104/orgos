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

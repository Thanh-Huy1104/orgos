"""Overall Definition of Done (Fix §C10) — run the spec's own tests.

The biggest blind spot orgos has had: even after `orgos deliver` says
"32 of 37 stories done", the answer to "does the code actually work" was
a human's job. This module closes that loop by executing the built code's
own test suite in the integration worktree and rolling the verdict into
the delivery-receipt.

Design:
  - Create a venv scoped to the integration worktree (or reuse one).
  - `pip install -e .` in the built package. Skip on failure (many
    goals won't produce an installable package early on).
  - Run `pytest -q` with a timeout. Capture pass/fail counts.
  - If pytest is missing or install fails, mark as "not verified"
    (not "failed") — absence of test infra != code doesn't work.
  - Return a VerificationResult that `orgos ship` can gate on and
    `orgos deliver` folds into the receipt.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import re as _re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class VerificationResult:
    verified: bool                          # True only when pytest ran to completion
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    coverage_pct: Optional[float] = None
    exit_code: Optional[int] = None
    duration_seconds: float = 0.0
    reason_not_verified: str = ""           # populated when verified=False
    install_ok: bool = False
    stdout_tail: str = ""
    collection_errors: list = field(default_factory=list)  # §H8 — files pytest couldn't parse

    @property
    def total_collected(self) -> int:
        return self.passed + self.failed + self.errors + self.skipped

    @property
    def pass_rate(self) -> float:
        n = self.passed + self.failed + self.errors
        return (self.passed / n) if n else 0.0

    def summary(self) -> str:
        if not self.verified:
            return f"NOT VERIFIED: {self.reason_not_verified}"
        parts = [f"{self.passed} passed"]
        if self.failed: parts.append(f"{self.failed} failed")
        if self.errors: parts.append(f"{self.errors} errors")
        if self.skipped: parts.append(f"{self.skipped} skipped")
        pct = f"{self.pass_rate * 100:.0f}%"
        tail = ""
        if self.collection_errors:
            tail = f" [+ {len(self.collection_errors)} files unparseable — skipped]"
        return f"pytest: {', '.join(parts)} ({pct} of runnable){tail}"


# Regexes for pytest -q's tail line: "5 passed, 2 failed, 1 skipped in 3.42s"
_COUNT_RE = re.compile(r"(\d+)\s+(passed|failed|error|errors|skipped|warning|warnings)")
_TIME_RE = re.compile(r"in\s+([\d.]+)s")


def _parse_pytest_output(stdout: str) -> dict:
    """Extract counts from pytest -q's summary line. Returns a dict of
    {passed, failed, errors, skipped, duration_seconds}. Missing keys are 0."""
    counts = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    duration = 0.0
    # Scan bottom-up — pytest puts its summary at the end.
    for line in reversed(stdout.splitlines()[-30:]):
        for m in _COUNT_RE.finditer(line):
            n, label = int(m.group(1)), m.group(2)
            if label in ("error", "errors"):
                counts["errors"] += n
            elif label in ("warning", "warnings"):
                pass  # ignore warnings for pass-rate math
            else:
                counts[label] += n
        tm = _TIME_RE.search(line)
        if tm and duration == 0.0:
            try:
                duration = float(tm.group(1))
            except ValueError:
                pass
        # First line with counts is usually the summary — stop there.
        if any(c > 0 for c in counts.values()):
            break
    return {**counts, "duration_seconds": duration}


def _repo_looks_installable(worktree: Path) -> bool:
    """True when pip install -e . is worth attempting."""
    return any(
        (worktree / f).exists()
        for f in ("pyproject.toml", "setup.py", "setup.cfg")
    )


def _pip_install_editable(worktree: Path, venv_python: str,
                          timeout: int = 180) -> tuple[bool, str]:
    """Best-effort pip install -e . in the worktree. Returns (ok, tail_of_stdout)."""
    try:
        r = subprocess.run(
            [venv_python, "-m", "pip", "install", "-e", ".", "--quiet"],
            cwd=str(worktree), capture_output=True, text=True, timeout=timeout,
        )
        return r.returncode == 0, ((r.stderr or "") + (r.stdout or ""))[-800:]
    except subprocess.TimeoutExpired:
        return False, "install timeout after 180s"
    except (OSError, subprocess.SubprocessError) as e:
        return False, f"install error: {e}"


def _ensure_venv(worktree: Path) -> Optional[str]:
    """Create a venv at worktree/.orgos_venv if missing. Returns venv python path."""
    venv_dir = worktree / ".orgos_venv"
    venv_python = str(venv_dir / ("Scripts" if os.name == "nt" else "bin") / "python")
    if Path(venv_python).exists():
        return venv_python
    try:
        subprocess.run(
            [sys.executable, "-m", "venv", str(venv_dir)],
            check=True, capture_output=True, timeout=60,
        )
        return venv_python
    except (subprocess.SubprocessError, OSError):
        return None


def verify_integration(
    *,
    integration_worktree: Path,
    pytest_args: Optional[list[str]] = None,
    timeout_seconds: int = 240,
    use_venv: bool = True,
    reuse_current_python: bool = False,
) -> VerificationResult:
    """Run the integration worktree's own test suite.

    Args:
      integration_worktree: path to the team's integration worktree
        (contains the code the team built).
      pytest_args: extra args to append to `pytest -q` (default none).
      timeout_seconds: kill the pytest run after this many seconds.
      use_venv: create/reuse .orgos_venv in the worktree. Set False for
        `reuse_current_python=True` fast-path in tests.
      reuse_current_python: skip venv + pip install and just run the
        current interpreter's pytest against the worktree. Only safe when
        the current process's pytest can find the built package (adds
        worktree to sys.path via PYTHONPATH). Used in tests.
    """
    integration_worktree = Path(integration_worktree)
    if not integration_worktree.exists():
        return VerificationResult(
            verified=False,
            reason_not_verified=f"integration worktree not found: {integration_worktree}",
        )

    # Fast path — reuse this process's interpreter. Only for tests.
    if reuse_current_python:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(integration_worktree) + os.pathsep + env.get("PYTHONPATH", "")
        try:
            r = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", *(pytest_args or [])],
                cwd=str(integration_worktree), env=env,
                capture_output=True, text=True, timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return VerificationResult(
                verified=False,
                reason_not_verified=f"pytest timeout after {timeout_seconds}s",
            )
        counts = _parse_pytest_output(r.stdout + "\n" + r.stderr)
        return VerificationResult(
            verified=True, install_ok=True,
            passed=counts["passed"], failed=counts["failed"],
            errors=counts["errors"], skipped=counts["skipped"],
            duration_seconds=counts["duration_seconds"],
            exit_code=r.returncode,
            stdout_tail=(r.stdout or "")[-800:],
        )

    # Production path — venv + editable install + pytest
    if not _repo_looks_installable(integration_worktree):
        return VerificationResult(
            verified=False,
            reason_not_verified=(
                "no pyproject.toml/setup.py in integration worktree — "
                "spec didn't produce an installable package (yet)"
            ),
        )

    if not use_venv:
        venv_python = sys.executable
    else:
        venv_python = _ensure_venv(integration_worktree)
        if venv_python is None:
            return VerificationResult(
                verified=False,
                reason_not_verified="could not create venv (python -m venv failed)",
            )

    install_ok, install_tail = _pip_install_editable(integration_worktree, venv_python)
    if not install_ok:
        return VerificationResult(
            verified=False, install_ok=False,
            reason_not_verified=f"pip install failed: {install_tail[:300]}",
        )

    def _run_pytest(extra_args: list[str]) -> tuple[Optional[subprocess.CompletedProcess], Optional[str]]:
        """Return (completed_process, error_string_or_None)."""
        try:
            proc = subprocess.run(
                [venv_python, "-m", "pytest", "-q", *(pytest_args or []), *extra_args],
                cwd=str(integration_worktree),
                capture_output=True, text=True, timeout=timeout_seconds,
            )
            return proc, None
        except subprocess.TimeoutExpired:
            return None, f"pytest timeout after {timeout_seconds}s"
        except (OSError, subprocess.SubprocessError) as e:
            return None, f"pytest subprocess error: {e}"

    r, err = _run_pytest([])
    if err:
        return VerificationResult(
            verified=False, install_ok=install_ok,
            reason_not_verified=err,
        )

    # §H8 — pytest aborts collection entirely when any test file has a syntax
    # error. Real LLM-produced code often has one broken file among many.
    # When we see "errors during collection", parse out the offending files
    # and retry with --ignore for each. Report both the pass count AND the
    # unparseable files so the user sees the reality: "121 passed but 2
    # files couldn't even be parsed by python's ast."
    combined = (r.stdout or "") + "\n" + (r.stderr or "")
    collection_errors: list[str] = []
    if "errors during collection" in combined or "error in " in combined:
        # Extract file paths from lines like "ERROR tests/foo/test_bar.py"
        for line in combined.splitlines():
            m = _re.match(r"^ERROR\s+(\S+\.py)", line.strip())
            if m:
                collection_errors.append(m.group(1))
        # Also try lines like "test_foo.py::test_x - error"
        if not collection_errors:
            for line in combined.splitlines():
                m = _re.search(r"(\S+/test_\w+\.py):\d+:", line)
                if m and m.group(1) not in collection_errors:
                    collection_errors.append(m.group(1))
        # Retry pytest ignoring the broken files, so the caller sees the
        # actual pass count of the parseable ones.
        if collection_errors:
            ignore_args: list[str] = []
            for f in collection_errors[:20]:  # cap so we don't build a huge cmd
                ignore_args.extend(["--ignore", f])
            r2, err2 = _run_pytest(ignore_args)
            if r2 is not None:
                r = r2  # use the retry result

    counts = _parse_pytest_output((r.stdout or "") + "\n" + (r.stderr or ""))
    return VerificationResult(
        verified=True, install_ok=True,
        passed=counts["passed"], failed=counts["failed"],
        errors=counts["errors"], skipped=counts["skipped"],
        duration_seconds=counts["duration_seconds"],
        exit_code=r.returncode,
        stdout_tail=(r.stdout or "")[-800:],
        collection_errors=collection_errors,
    )

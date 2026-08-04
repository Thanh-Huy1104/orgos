#!/usr/bin/env python3
"""Score a target repo against the held-out reference test suite.

Usage:
    python scripts/score_reftests.py --target C:/temp/minisearch-copilot [--label solo-1]

Copies docs/specs/minisearch_reftests/ into <target>/tests/_reftests,
runs `pip install -e .` in a fresh subprocess, then runs pytest against
just the reference tests and emits a JSON summary to stdout.

The pass count out of the reftests total is the arm's **reference-suite
pass rate** — the metric that is not self-graded by the arm's own tests.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import shutil
import subprocess
import sys
import time


ROOT = pathlib.Path(__file__).resolve().parent.parent
REFTESTS = ROOT / "docs" / "specs" / "minisearch_reftests"
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"


def copy_reftests(target: pathlib.Path) -> pathlib.Path:
    dest = target / "tests" / "_reftests"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(REFTESTS, dest)
    return dest


def pip_install_editable(target: pathlib.Path) -> tuple[bool, str]:
    """Best-effort install so the reftests can import the package."""
    r = subprocess.run(
        [str(VENV_PY), "-m", "pip", "install", "-e", ".", "-q",
         "--disable-pip-version-check"],
        cwd=str(target), capture_output=True, text=True, timeout=300,
    )
    return r.returncode == 0, (r.stdout + r.stderr)


def run_pytest(target: pathlib.Path) -> tuple[int, str]:
    r = subprocess.run(
        [str(VENV_PY), "-m", "pytest", "tests/_reftests",
         "--tb=no", "--no-header",
         "--continue-on-collection-errors",
         "-p", "no:cacheprovider"],
        cwd=str(target), capture_output=True, text=True, timeout=600,
    )
    return r.returncode, r.stdout + r.stderr


# ─── Parse pytest tail lines ─────────────────────────────────────────────
# Examples we handle:
#   "12 passed, 3 failed, 1 skipped, 2 warnings in 4.32s"
#   "42 passed in 3.10s"
#   "5 failed, 20 passed in 2.11s"
#   "5 errors in 1.10s"
_COUNTS = re.compile(r"(\d+)\s+(passed|failed|errors?|skipped|xfailed|xpassed)")

# pytest final line pattern: "===== 22 failed, 87 passed, 1 skipped in 4.32s ====="
# (may be preceded by a "short test summary info" block with many FAILED lines)
_SUMMARY_LINE = re.compile(
    r"^=+\s*(?:\d+\s+(?:passed|failed|errors?|skipped|xfailed|xpassed)(?:,\s+)?)+.*=+\s*$",
    re.MULTILINE,
)


def parse_counts(output: str) -> dict:
    counts = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    # First try to find the summary banner line (most reliable).
    matches = _SUMMARY_LINE.findall(output)
    summary_text = matches[-1] if matches else output  # fallback to whole output
    for n, kind in _COUNTS.findall(summary_text):
        key = "errors" if kind.startswith("error") else kind
        if key in counts:
            counts[key] = int(n)
    # If we still have all zeros but pytest clearly ran, scan the whole text
    # for the last summary-style occurrence anywhere.
    if sum(counts.values()) == 0:
        for n, kind in _COUNTS.findall(output):
            key = "errors" if kind.startswith("error") else kind
            if key in counts:
                counts[key] = max(counts[key], int(n))
    counts["total"] = sum(counts.values())
    counts["pct_pass"] = round(
        100.0 * counts["passed"] / counts["total"], 1
    ) if counts["total"] else 0.0
    return counts


def score(target: pathlib.Path, label: str) -> dict:
    t0 = time.time()
    copy_reftests(target)
    ok, install_out = pip_install_editable(target)
    exit_code, pytest_out = run_pytest(target)
    counts = parse_counts(pytest_out)
    return {
        "label": label,
        "target": str(target),
        "reftests_source": str(REFTESTS),
        "install_ok": ok,
        "install_tail": install_out.splitlines()[-8:] if install_out else [],
        "pytest_exit_code": exit_code,
        "counts": counts,
        "pytest_tail": pytest_out.splitlines()[-20:],
        "wall_seconds": round(time.time() - t0, 2),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True,
                     help="Path to the arm's target repo")
    ap.add_argument("--label", default=None,
                     help="Label for this run (e.g. 'ms1', 'copilot-solo-2')")
    ap.add_argument("--out", default=None,
                     help="Write full JSON to this path (defaults to stdout)")
    args = ap.parse_args()

    target = pathlib.Path(args.target).resolve()
    if not target.exists():
        print(f"target not found: {target}", file=sys.stderr)
        sys.exit(2)

    label = args.label or target.name
    result = score(target, label)
    dump = json.dumps(result, indent=2)

    if args.out:
        pathlib.Path(args.out).write_text(dump, encoding="utf-8")
    print(dump)

    # Human-readable one-liner to stderr
    c = result["counts"]
    print(f"\n[{label}] {c['passed']}/{c['total']} passed "
          f"({c['pct_pass']}%) — reference-suite pass rate",
          file=sys.stderr)


if __name__ == "__main__":
    main()

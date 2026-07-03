"""Demo seed: run N sprints back-to-back with a fixture backlog."""

from __future__ import annotations

import argparse
from pathlib import Path

from orgos.agile.sprint import run_sprint


DEMO_ISSUES = [
    {"issue_id": "demo-1", "title": "Add farewell()",
     "body": "Add `farewell()` -> 'bye' to src.py + test.", "labels": ["agent-eligible"]},
    {"issue_id": "demo-2", "title": "Add greeting_uppercase()",
     "body": "Add `greeting_uppercase()` returning greet().upper().", "labels": ["agent-eligible"]},
    {"issue_id": "demo-3", "title": "Type-hint src.py",
     "body": "Add type hints to src.py functions.", "labels": ["agent-eligible"]},
    {"issue_id": "demo-4", "title": "Add doctest to greet()",
     "body": "Add a doctest to greet().", "labels": ["agent-eligible"]},
    {"issue_id": "demo-5", "title": "Extract constants",
     "body": "Move return strings to module-level constants.", "labels": ["agent-eligible"]},
]

HARD_ISSUE = {
    "issue_id": "hard-1",
    "title": "Rename greet() -> welcome() everywhere, preserving external API",
    "body": (
        "Rename greet() -> welcome(). All existing callers must continue to work "
        "(add greet = welcome shim). Update all tests. Do not modify README. "
        "Diff must stay under 40 LOC total."
    ),
    "labels": ["agent-eligible"],
}


def seed(n: int, repo: Path, include_hard: bool = False) -> None:
    issues = list(DEMO_ISSUES)
    if include_hard:
        issues.insert(n // 2, HARD_ISSUE)
    for i, issue in enumerate(issues[:n]):
        s = run_sprint(repo, issue, mock_pr=True)
        print(f"sprint {i+1}/{n}: id={s.id} status={s.status}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    seed_cmd = sub.add_parser("seed")
    seed_cmd.add_argument("--sprints", type=int, default=5)
    seed_cmd.add_argument("--repo", default=".")
    seed_cmd.add_argument("--include-hard", action="store_true")
    args = ap.parse_args()
    if args.cmd == "seed":
        seed(args.sprints, Path(args.repo), include_hard=args.include_hard)


if __name__ == "__main__":
    main()

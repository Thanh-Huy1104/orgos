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


def seed(n: int, repo: Path) -> None:
    for i in range(n):
        issue = DEMO_ISSUES[i % len(DEMO_ISSUES)]
        s = run_sprint(repo, issue, mock_pr=True)
        print(f"sprint {i+1}/{n}: id={s.id} status={s.status}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    seed_cmd = sub.add_parser("seed")
    seed_cmd.add_argument("--sprints", type=int, default=5)
    seed_cmd.add_argument("--repo", default=".")
    args = ap.parse_args()
    if args.cmd == "seed":
        seed(args.sprints, Path(args.repo))


if __name__ == "__main__":
    main()

"""Run one dogfood sprint proving the fixes:
  - Engineer commits its own change to the worktree branch
  - Sprint captures subordinate envelopes (not just the summary)

Uses a small self-referential cleanup issue — proves the framework can
edit itself + persist the whole envelope chain.
"""
from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    from orgos.agile.sprint import run_sprint

    issue = {
        "issue_id": "cleanup-dora-json-import",
        "title": "Delete unused `import json` from tests/agile/test_dora.py",
        "body": (
            "tests/agile/test_dora.py has `import json` and `from pathlib "
            "import Path` at the top but neither is used — the file uses "
            "pytest.approx and datetime only.\n\n"
            "Task:\n"
            "- Open tests/agile/test_dora.py.\n"
            "- Delete the `import json` line and the `from pathlib import Path` line.\n"
            "- Do not modify any other file, function, or test.\n"
            "- Run pytest tests/agile/test_dora.py to confirm nothing broke.\n"
            "- Commit the change to the worktree branch (Engineer instructions "
            "in the sprint brief tell you how)."
        ),
        "labels": ["agent-eligible", "cleanup"],
    }

    model = os.environ.get("LEVEL_B_MODEL", "deepseek/deepseek-v4-pro")
    print(f"Repo         : {REPO_ROOT}")
    print(f"Model        : {model}")
    print(f"Issue        : {issue['title']}")
    print()

    sprint = run_sprint(
        REPO_ROOT,
        issue,
        model=model,
        mock_pr=True,
        run_budget_tokens=800_000,
    )

    print()
    print(f"Sprint id    : {sprint.id}")
    print(f"Branch       : {sprint.branch}")
    print(f"Worktree     : {sprint.worktree_path}")
    print(f"Status       : {sprint.status}")
    print(f"Envelopes    : {sorted(sprint.envelopes.keys())}")

    summary = sprint.envelopes.get("summary")
    if summary is not None:
        print()
        print("=== Sprint Lead summary ===")
        print(summary.summary[:800])

    # Show git log inside the worktree — did the Engineer commit?
    import subprocess
    log = subprocess.run(
        ["git", "-C", str(sprint.worktree_path), "log", "--oneline", "-5"],
        capture_output=True, text=True,
    )
    print()
    print("=== Worktree git log ===")
    print(log.stdout)

    print(f"To inspect the diff:  git -C {sprint.worktree_path} diff HEAD~1 HEAD")


if __name__ == "__main__":
    main()

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
        "issue_id": "cleanup-attribution-import-json",
        "title": "Remove unused `import json` from orgos/agile/attribution.py",
        "body": (
            "orgos/agile/attribution.py imports json at the top but never "
            "uses it directly — the module uses `json.dumps` on the null "
            "envelopes but those calls appear before the constant is "
            "referenced. Wait — actually double-check: `import json` may or "
            "may not be used. If it IS used, do nothing and report the "
            "envelope's status as needs_revision with a note.\n\n"
            "Task:\n"
            "- Read orgos/agile/attribution.py carefully.\n"
            "- If `import json` is unused, remove it.\n"
            "- If `import json` IS used somewhere in the file, do NOT remove "
            "  it — report needs_revision instead. Do not delete anything else.\n"
            "- Run pytest tests/agile/test_attribution.py to confirm nothing broke.\n"
            "- Commit the change to the worktree branch."
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

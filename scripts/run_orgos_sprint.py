"""Run one sprint against the orgos repo itself (dogfooding).

Unlike scripts/run_level_b.py this points the Engineer at the LIVE orgos
codebase — the worktree is a fork of the current HEAD, so the Engineer
sees the real code. mock_pr=True keeps things safe (no real PR opened);
we inspect the diff manually in .sprints/<id>/ afterwards.

Usage:
    set -a; source .env; set +a
    PYTHONPATH=. python scripts/run_orgos_sprint.py

Cost: ~$0.05-0.20 per sprint on deepseek/deepseek-v4-pro depending on
how much of the repo the Engineer reads before landing the change.
"""
from __future__ import annotations

import os
from pathlib import Path

# Point at the actual orgos repo, one level up from scripts/.
REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    from orgos.agile.sprint import run_sprint

    # This is the exact issue the reviewer flagged. Purpose-shaped to match
    # what a well-labelled `agent-eligible` GitHub issue would look like.
    issue = {
        "issue_id": "cleanup-dora-within",
        "title": "Delete unused _within helper in orgos/agile/dora.py",
        "body": (
            "The _within(dt, window_start) helper at orgos/agile/dora.py:28 "
            "is defined but never called. compute_dora enforces the window "
            "boundary in SQL directly ('AND created_at >= ?'), so _within "
            "is dead code left over from an earlier draft.\n\n"
            "Task:\n"
            "- Delete the _within function definition from orgos/agile/dora.py.\n"
            "- Run pytest tests/agile/test_dora.py to confirm nothing broke.\n"
            "- Do not modify any other file. Do not touch compute_dora or "
            "  classify_tier. The diff should be under 5 lines total."
        ),
        "labels": ["agent-eligible", "cleanup"],
    }

    model = os.environ.get("LEVEL_B_MODEL", "deepseek/deepseek-v4-pro")
    print(f"Repo          : {REPO_ROOT}")
    print(f"Model         : {model}")
    print(f"Issue         : {issue['title']}")
    print()

    sprint = run_sprint(
        REPO_ROOT,
        issue,
        model=model,
        mock_pr=True,
        run_budget_tokens=800_000,
    )

    print()
    print(f"Sprint id     : {sprint.id}")
    print(f"Branch        : {sprint.branch}")
    print(f"Worktree      : {sprint.worktree_path}")
    print(f"Status        : {sprint.status}")
    print(f"Envelopes     : {sorted(sprint.envelopes.keys())}")

    summary = sprint.envelopes.get("summary")
    if summary is not None:
        print()
        print("=== Sprint Lead summary ===")
        print(summary.summary[:1200])
        print()

    print(f"To inspect the diff:  git -C {sprint.worktree_path} diff HEAD")
    print(f"To clean up:          rm -rf {sprint.worktree_path} "
          f"&& git -C {REPO_ROOT} worktree prune")


if __name__ == "__main__":
    main()

"""Run two small cleanup sprints back-to-back on the orgos repo.

Each sprint is a separate call to run_sprint(), separate PMStore row,
separate worktree, mock PR only.
"""
from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

ISSUES = [
    {
        "issue_id": "cleanup-conftest-tempfile",
        "title": "Remove leftover import tempfile from tests/agile/conftest.py",
        "body": (
            "tests/agile/conftest.py imports `tempfile` at the top but never "
            "uses it — the fixture_repo fixture takes tmp_path from pytest "
            "so no tempfile calls are needed.\n\n"
            "Task:\n"
            "- Remove the `import tempfile` line from tests/agile/conftest.py.\n"
            "- Do not modify any other file or any other line.\n"
            "- Run pytest tests/agile/ to confirm nothing broke."
        ),
        "labels": ["agent-eligible", "cleanup"],
    },
    {
        "issue_id": "cleanup-attribution-envelope-import",
        "title": "Delete unused HandoffEnvelope import from orgos/agile/attribution.py",
        "body": (
            "orgos/agile/attribution.py imports HandoffEnvelope but never "
            "references it directly — the module only uses the subclass "
            "envelopes.\n\n"
            "Task:\n"
            "- Open orgos/agile/attribution.py and remove HandoffEnvelope "
            "  from its imports (it's likely imported from .envelopes).\n"
            "- Keep the other imports (BriefEnvelope, EngineeringEnvelope, "
            "  ReleaseEnvelope, GradeEnvelope if present) untouched.\n"
            "- Do not modify any other file.\n"
            "- Run pytest tests/agile/test_attribution.py to confirm."
        ),
        "labels": ["agent-eligible", "cleanup"],
    },
]


def main() -> None:
    from orgos.agile.sprint import run_sprint

    model = os.environ.get("LEVEL_B_MODEL", "deepseek/deepseek-v4-pro")

    for i, issue in enumerate(ISSUES, 1):
        print("=" * 70)
        print(f"Sprint {i}/{len(ISSUES)}: {issue['title']}")
        print("=" * 70)

        sprint = run_sprint(
            REPO_ROOT,
            issue,
            model=model,
            mock_pr=True,
            run_budget_tokens=800_000,
        )

        print()
        print(f"  sprint_id : {sprint.id}")
        print(f"  status    : {sprint.status}")
        print(f"  worktree  : {sprint.worktree_path}")
        summary = sprint.envelopes.get("summary")
        if summary is not None:
            print(f"  synth     : {summary.summary[:200]}...")
        print()


if __name__ == "__main__":
    main()

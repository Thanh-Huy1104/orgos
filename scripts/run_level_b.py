"""Level B: run one full sprint against a throwaway fixture repo.

Uses deepseek-chat as the model (cheap, ~$0.01/sprint on average). Creates a
fresh git repo in /tmp with a trivial src.py, feeds the sprint one synthetic
issue, and lets the whole 5-role team + rubric + PMStore write path run
end-to-end. PR opening is mocked (mock://pr/...) — no GitHub needed.

Usage:
    PYTHONPATH=. python scripts/run_level_b.py
"""
from __future__ import annotations

import subprocess
import tempfile
import textwrap
from pathlib import Path


def make_fixture_repo() -> Path:
    """Build a tiny git repo the sprint can operate on."""
    root = Path(tempfile.mkdtemp(prefix="orgos-level-b-"))
    (root / "src.py").write_text(textwrap.dedent("""\
        def greet() -> str:
            return "hello"
    """))
    (root / "test_src.py").write_text(textwrap.dedent("""\
        from src import greet


        def test_greet() -> None:
            assert greet() == "hello"
    """))
    (root / "README.md").write_text("# level-b fixture repo\n")

    def _git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=root, check=True,
                       capture_output=True, text=True)

    _git("init", "-q", "-b", "main")
    _git("config", "user.email", "level-b@orgos.local")
    _git("config", "user.name", "orgos-level-b")
    _git("add", "-A")
    _git("commit", "-q", "-m", "init fixture repo")
    return root


def main() -> None:
    from orgos.agile.sprint import run_sprint

    issue = {
        "issue_id": "levelb-1",
        "title": "Add farewell() function to src.py",
        "body": (
            "Add a farewell() function to src.py that returns the string 'bye'. "
            "Also add a test in test_src.py verifying it. "
            "Keep the diff under 20 lines. "
            "Do not modify existing greet()."
        ),
        "labels": ["agent-eligible"],
    }

    print("== Level B sprint ==")
    repo = make_fixture_repo()
    print(f"Fixture repo: {repo}")

    sprint = run_sprint(
        repo,
        issue,
        model="deepseek/deepseek-chat",  # cheap
        mock_pr=True,                    # no GitHub
        run_budget_tokens=200_000,
    )

    print()
    print(f"Sprint id     : {sprint.id}")
    print(f"Branch        : {sprint.branch}")
    print(f"Worktree      : {sprint.worktree_path}")
    print(f"Status        : {sprint.status}")
    print(f"Envelopes     : {sorted(sprint.envelopes.keys())}")

    grade = sprint.envelopes.get("grade")
    if grade is not None:
        p = grade.parsed_payload()
        print(f"Rubric score  : {p.get('rubric_score', '?')}")
        for c in p.get("criteria", []):
            mark = "PASS" if c["passed"] else "FAIL"
            print(f"  [{mark}] {c['name']:22} — {c.get('reason', '')[:70]}")

    release = sprint.envelopes.get("release")
    if release is not None:
        p = release.parsed_payload()
        print(f"PR URL        : {p.get('pr_url')}  (mock={p.get('mock_mode')})")

    print()
    print("Refresh http://localhost:3000/sprints — this sprint should be at the top.")


if __name__ == "__main__":
    main()

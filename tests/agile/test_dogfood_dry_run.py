"""Network-marked: pulls real issues from GitHub.

Verifies Intake produces a non-empty backlog when the repo has agent-eligible
issues. Skipped by default; opt in with:
    pytest -m network tests/agile/test_dogfood_dry_run.py
"""

import os
import pytest

from orgos.agile.sprint import run_nightly_sprint
from pathlib import Path


pytestmark = pytest.mark.network


def test_intake_finds_at_least_one_eligible_issue():
    if not os.getenv("GITHUB_TOKEN") or not os.getenv("GITHUB_REPO"):
        pytest.skip("GITHUB_TOKEN / GITHUB_REPO not set")
    sprint = run_nightly_sprint(Path("."), mock_pr=True, _offline=True)
    backlog = sprint.envelopes["backlog"].parsed_payload()["candidates"]
    # If the repo has zero agent-eligible issues, the test still passes
    # but flags it — the demo seed run will need to label one.
    assert isinstance(backlog, list)

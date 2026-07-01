"""Skeleton-sprint smoke test. Uses ollama/llama3.2 if available, else
mocks the spawn layer to keep the test offline+fast in CI."""

import json
import os
from pathlib import Path

import pytest

from orgos.agile.envelopes import (
    BriefEnvelope, EngineeringEnvelope, GradeEnvelope, ReleaseEnvelope,
)


_SPAWN_SMOKE = pytest.mark.skipif(
    os.getenv("ORGOS_RUN_SPAWN_SMOKE") != "1",
    reason="Live spawn smoke; gated behind ORGOS_RUN_SPAWN_SMOKE=1",
)


@_SPAWN_SMOKE
def test_run_sprint_produces_full_envelope_chain(fixture_repo: Path):
    from orgos.agile.sprint import run_sprint

    issue = {
        "issue_id": "demo-1",
        "title": "Add a farewell function",
        "body": "Add `farewell()` returning 'bye' to src.py. Update tests.",
        "labels": ["agent-eligible"],
    }
    sprint = run_sprint(fixture_repo, issue, mock_pr=True)

    for key in ("brief", "engineering", "grade", "release"):
        assert key in sprint.envelopes, f"missing envelope: {key}"
    assert isinstance(sprint.envelopes["brief"], BriefEnvelope)
    assert isinstance(sprint.envelopes["engineering"], EngineeringEnvelope)
    assert isinstance(sprint.envelopes["grade"], GradeEnvelope)
    assert isinstance(sprint.envelopes["release"], ReleaseEnvelope)

    # The release envelope must be a mock PR in this mode.
    assert sprint.envelopes["release"].parsed_payload()["mock_mode"] is True
    assert sprint.status in {"completed", "needs_revision"}


@_SPAWN_SMOKE
def test_run_sprint_creates_worktree_under_dot_sprints(fixture_repo: Path):
    from orgos.agile.sprint import run_sprint
    sprint = run_sprint(fixture_repo, {
        "issue_id": "demo-2", "title": "noop", "body": "noop", "labels": [],
    }, mock_pr=True)
    assert sprint.worktree_path.exists()
    assert ".sprints" in str(sprint.worktree_path)


def test_sprint_dataclass_shape():
    from orgos.agile.sprint import Sprint
    s = Sprint(
        id="x", started_at="2026-06-30T00:00:00Z",
        repo_path=Path("."), worktree_path=Path("."),
        branch="agile/x", picked_issue={"issue_id": "1"},
        envelopes={}, status="in_progress",
    )
    assert s.status == "in_progress"

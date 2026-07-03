import json
import pytest
from pathlib import Path

from orgos.agile.envelopes import (
    BacklogEnvelope, BriefEnvelope, EngineeringEnvelope,
    GradeEnvelope, ReleaseEnvelope, RetroEnvelope,
)
from orgos.agile.attribution import compute_attribution
from orgos.agile.sprint import Sprint


def _make_sprint(rubric_score: float = 1.0) -> Sprint:
    e = EngineeringEnvelope(
        role="engineer", status="completed", summary="",
        success_criteria_met=True, requires_human_approval=False,
        payload=json.dumps({
            "diff": "+x\n", "commit_sha": "abc1234",
            "files_touched": ["src.py"],
            "test_command": "pytest test_src.py",
            "test_output": "ok", "test_passed": True,
        }),
    )
    b = BriefEnvelope(
        role="pm", status="completed", summary="",
        success_criteria_met=True, requires_human_approval=False,
        payload=json.dumps({
            "picked_issue_id": "1", "task_brief_json": "{}",
            "touched_files_allowlist": ["src.py"],
            "acceptance_tests": ["pytest test_src.py"],
        }),
    )
    g = GradeEnvelope(
        role="qa", status="completed", summary="",
        success_criteria_met=True, requires_human_approval=False,
        payload=json.dumps({
            "criteria": [], "rubric_score": rubric_score,
        }),
    )
    r = ReleaseEnvelope(
        role="release", status="completed", summary="",
        success_criteria_met=True, requires_human_approval=False,
        payload=json.dumps({"pr_url": "mock://pr/1", "branch": "agile/x",
                            "mock_mode": True}),
    )
    return Sprint(
        id="s1", started_at="", repo_path=Path("."), worktree_path=Path("."),
        branch="agile/s1", picked_issue={"issue_id": "1"},
        envelopes={"brief": b, "engineering": e, "grade": g, "release": r},
        status="completed",
    )


def test_attribution_sums_to_one():
    scores = compute_attribution(_make_sprint())
    assert sum(scores.values()) == pytest.approx(1.0, abs=0.02)


def test_pm_and_engineer_both_positive():
    scores = compute_attribution(_make_sprint())
    assert scores["product-manager"] > 0
    assert scores["engineer"] > 0


def test_zero_rubric_score_gives_uniform_attribution():
    """When nothing worked, no role gets credit — split equally so the row exists."""
    scores = compute_attribution(_make_sprint(rubric_score=0.0))
    vals = list(scores.values())
    assert max(vals) - min(vals) < 0.01

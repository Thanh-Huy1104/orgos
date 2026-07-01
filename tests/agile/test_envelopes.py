import json

import pytest

from orgos.agile.envelopes import (
    BacklogEnvelope, BriefEnvelope, EngineeringEnvelope,
    GradeEnvelope, ReleaseEnvelope, RetroEnvelope, DoraEnvelope,
)


def _base(**over):
    base = dict(
        role="x", status="completed", summary="ok",
        success_criteria_met=True, requires_human_approval=False,
    )
    base.update(over)
    return base


def test_backlog_envelope_payload_round_trip():
    env = BacklogEnvelope(**_base(
        payload=json.dumps({"candidates": [
            {"issue_id": "42", "title": "fix typo", "size": "S", "risk": "low"}
        ]})
    ))
    data = json.loads(env.payload)
    assert data["candidates"][0]["issue_id"] == "42"


def test_brief_envelope_requires_payload_fields():
    env = BriefEnvelope(**_base(
        payload=json.dumps({
            "picked_issue_id": "42",
            "task_brief_json": "{}",
            "touched_files_allowlist": ["src.py"],
            "acceptance_tests": ["pytest test_src.py"],
        })
    ))
    parsed = env.parsed_payload()
    assert parsed["picked_issue_id"] == "42"


def test_engineering_envelope_payload():
    env = EngineeringEnvelope(**_base(
        payload=json.dumps({
            "diff": "--- a\n+++ b\n",
            "commit_sha": "abc123",
            "files_touched": ["src.py"],
            "test_command": "pytest",
            "test_output": "1 passed",
            "test_passed": True,
        })
    ))
    assert env.parsed_payload()["test_passed"] is True


def test_grade_envelope_score_in_range():
    env = GradeEnvelope(**_base(
        payload=json.dumps({
            "criteria": [{"name": "tests_pass", "passed": True, "reason": ""}],
            "rubric_score": 1.0,
        })
    ))
    assert 0.0 <= env.parsed_payload()["rubric_score"] <= 1.0


def test_release_envelope_mock_mode():
    env = ReleaseEnvelope(**_base(
        payload=json.dumps({"pr_url": None, "branch": "agile/abc", "mock_mode": True})
    ))
    assert env.parsed_payload()["mock_mode"] is True


def test_retro_envelope_attribution():
    env = RetroEnvelope(**_base(
        payload=json.dumps({
            "retro_markdown": "# retro",
            "candidate_heuristics": [{"rule": "x", "why": "y"}],
            "role_attribution": {"product_manager": 0.4, "engineer": 0.6},
        })
    ))
    assert sum(env.parsed_payload()["role_attribution"].values()) == pytest.approx(1.0)


def test_dora_envelope_tier():
    env = DoraEnvelope(**_base(
        payload=json.dumps({
            "deploy_freq": 1.2, "lead_time_p50": 18000.0,
            "cfr": 0.1, "mttr_p50": 3600.0, "tier": "Medium",
        })
    ))
    assert env.parsed_payload()["tier"] in {"Elite", "High", "Medium", "Low"}

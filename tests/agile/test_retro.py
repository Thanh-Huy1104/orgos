import json
from pathlib import Path

from orgos.agile.envelopes import RetroEnvelope
from orgos.agile.retro import build_retro_from_sprint
from orgos.agile.sprint import Sprint


def test_offline_retro_uses_attribution_scores():
    from orgos.agile.envelopes import (
        BriefEnvelope, EngineeringEnvelope, GradeEnvelope, ReleaseEnvelope,
    )
    envs = {
        "brief": BriefEnvelope(role="pm", status="completed", summary="",
            success_criteria_met=True, requires_human_approval=False,
            payload=json.dumps({"picked_issue_id": "1", "task_brief_json": "{}",
              "touched_files_allowlist": ["src.py"],
              "acceptance_tests": ["pytest"]})),
        "engineering": EngineeringEnvelope(role="e", status="completed",
            summary="", success_criteria_met=True, requires_human_approval=False,
            payload=json.dumps({"diff": "+x", "commit_sha": "abc1234",
              "files_touched": ["src.py"], "test_command": "pytest",
              "test_output": "ok", "test_passed": True})),
        "grade": GradeEnvelope(role="qa", status="completed", summary="",
            success_criteria_met=True, requires_human_approval=False,
            payload=json.dumps({"criteria": [], "rubric_score": 1.0})),
        "release": ReleaseEnvelope(role="r", status="completed", summary="",
            success_criteria_met=True, requires_human_approval=False,
            payload=json.dumps({"pr_url": "mock://pr/1", "branch": "agile/x",
              "mock_mode": True})),
    }
    sprint = Sprint(
        id="s1", started_at="", repo_path=Path("."), worktree_path=Path("."),
        branch="agile/s1", picked_issue={"issue_id": "1"},
        envelopes=envs, status="completed",
    )
    retro = build_retro_from_sprint(sprint)
    assert isinstance(retro, RetroEnvelope)
    payload = retro.parsed_payload()
    assert payload["role_attribution"]
    assert payload["retro_markdown"]

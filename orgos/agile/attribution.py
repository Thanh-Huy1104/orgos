"""Per-role marginal contribution — ablation-on-replay approximation.

For each role R, compute what QA's rubric_score would drop to if R's
envelope were null. Attribution(R) = (baseline - ablated_R) / sum(drops).
We normalise to sum to 1.0 so the rows are ratios, not raw drops.
"""

from __future__ import annotations

import json

from .envelopes import (
    BriefEnvelope, EngineeringEnvelope, GradeEnvelope,
    ReleaseEnvelope,
)
from .rubric import grade as run_rubric


_NULL_BRIEF = BriefEnvelope(
    role="pm", status="failed", summary="", success_criteria_met=False,
    requires_human_approval=False,
    payload=json.dumps({
        "picked_issue_id": "", "task_brief_json": "{}",
        "touched_files_allowlist": [],
        "acceptance_tests": [],
    }),
)
_NULL_ENG = EngineeringEnvelope(
    role="engineer", status="failed", summary="", success_criteria_met=False,
    requires_human_approval=False,
    payload=json.dumps({
        "diff": "", "commit_sha": "",
        "files_touched": [],
        "test_command": "",
        "test_output": "",
        "test_passed": False,
    }),
)


def compute_attribution(sprint) -> dict[str, float]:
    """Score each role's contribution to the sprint's rubric_score.

    We ablate one role at a time and re-grade the rubric with the null
    envelope substituted. The drop is that role's marginal contribution.

    Only PM and Engineer directly move the rubric (it grades their
    outputs). QA and Release get residual weight based on their envelope
    presence — a completed Release counts, a missing one does not.
    """
    env = sprint.envelopes
    if not (env.get("brief") and env.get("engineering") and env.get("grade")):
        return {"sprint-lead": 0.25, "product-manager": 0.25,
                "engineer": 0.25, "qa-validator": 0.15, "release-manager": 0.10}

    baseline = env["grade"].parsed_payload().get("rubric_score", 0.0)
    if baseline <= 0.0:
        # Uniform — no role earned credit.
        keys = ["sprint-lead", "product-manager", "engineer",
                "qa-validator", "release-manager"]
        return {k: 1.0 / len(keys) for k in keys}

    ablated_pm = run_rubric(_NULL_BRIEF, env["engineering"]).parsed_payload()["rubric_score"]
    ablated_eng = run_rubric(env["brief"], _NULL_ENG).parsed_payload()["rubric_score"]
    pm_drop = max(baseline - ablated_pm, 0.0)
    eng_drop = max(baseline - ablated_eng, 0.0)

    qa_signal = 0.10 if env.get("grade") else 0.0
    release_signal = 0.10 if env.get("release") else 0.0
    lead_signal = 0.05  # coordinator overhead

    raw = {
        "sprint-lead": lead_signal,
        "product-manager": pm_drop,
        "engineer": eng_drop,
        "qa-validator": qa_signal,
        "release-manager": release_signal,
    }
    total = sum(raw.values()) or 1.0
    return {k: round(v / total, 3) for k, v in raw.items()}

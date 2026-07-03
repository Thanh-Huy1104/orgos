"""Retro Agent — deterministic retrospective builder.

For MVP we skip the LLM call and generate a factual retro from the
envelope chain + attribution. A future task can swap in a real spawn()
that reads the audit log for prose retros; the deterministic version is
what the tests + demo rely on.
"""

from __future__ import annotations

import json

from .attribution import compute_attribution
from .envelopes import RetroEnvelope


def build_retro_from_sprint(sprint) -> RetroEnvelope:
    scores = compute_attribution(sprint)
    grade = sprint.envelopes.get("grade")
    grade_payload = grade.parsed_payload() if grade else {}
    rubric_score = grade_payload.get("rubric_score", 0.0)

    lines = [f"# Sprint {sprint.id} retro", ""]
    lines.append(f"- **Rubric score:** {rubric_score:.2f}")
    lines.append(f"- **Status:** {sprint.status}")
    lines.append("")
    lines.append("## Role contribution")
    for role, s in sorted(scores.items(), key=lambda x: -x[1]):
        lines.append(f"- {role}: {s:.2f}")

    failed = [c for c in grade_payload.get("criteria", []) if not c.get("passed")]
    candidates = []
    if failed:
        lines.append("")
        lines.append("## What didn't work")
        for c in failed:
            lines.append(f"- **{c['name']}** — {c.get('reason', '')}")
            candidates.append({
                "rule": f"Address {c['name']} in the DoD",
                "why": c.get("reason", "recurring failure mode"),
                "tags": [c["name"]],
            })
    payload = json.dumps({
        "retro_markdown": "\n".join(lines),
        "candidate_heuristics": candidates,
        "role_attribution": scores,
    })
    return RetroEnvelope(
        role="retro-agent", status="completed",
        summary=f"score={rubric_score:.2f}",
        success_criteria_met=True, requires_human_approval=False,
        payload=payload,
    )

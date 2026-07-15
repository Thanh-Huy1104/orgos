"""Dual-team paired benchmarking — SHA-pinned comparison on the same issue.

Runs the same issue against two different agent topologies (different
`agents/` directories), collecting rubric + DORA + flow-metric scores for
both runs. Produces a paired comparison report.

Used for measuring the effect of topology changes — the core publishable
contribution of the autonomous scrum team platform.

Usage:
    from orgos.agile.paired_run import run_paired_benchmark
    report = run_paired_benchmark(
        repo_path=Path("."),
        issue={"issue_id": "42", "title": "Fix login"},
        agents_dir_a=Path("agents"),
        agents_dir_b=Path("agents_alt"),
    )
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from orgos.agile.flow_metric import compute_flow_metrics, FlowMetricResult
from orgos.pm import PMStore


@dataclass
class TeamRunResult:
    team_name: str
    sprint_id: str
    started_at: str
    completed_at: str
    status: str
    rubric_score: float | None = None
    dora_tier: str = ""
    flow_score: float = 0.0
    quality_score: float = 0.0
    envelopes: dict[str, Any] = field(default_factory=dict)


@dataclass
class PairedRunReport:
    issue_id: str
    repo_sha: str
    created_at: str
    team_a: TeamRunResult
    team_b: TeamRunResult
    winner: str = "tie"
    score_delta: float = 0.0
    flow_delta: float = 0.0
    summary: str = ""


def _freeze_sha(repo: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo, check=True, capture_output=True, text=True,
    )
    return result.stdout.strip()


def _run_team_sprint(
    repo: Path,
    issue: dict,
    team_name: str,
    *,
    model: str | None = None,
    mock_pr: bool = True,
) -> TeamRunResult:
    from orgos.agile.sprint import run_sprint

    sprint = run_sprint(repo, issue, model=model, mock_pr=mock_pr)
    completed = datetime.now(timezone.utc).isoformat()

    rubric_score = None
    grade = sprint.envelopes.get("grade")
    if grade:
        try:
            payload = grade.parsed_payload() if hasattr(grade, "parsed_payload") else json.loads(grade.payload if hasattr(grade, "payload") else "{}")
            rubric_score = payload.get("rubric_score")
        except Exception:
            pass

    dora_tier = ""
    dora = sprint.envelopes.get("dora")
    if dora:
        try:
            payload = dora.parsed_payload() if hasattr(dora, "parsed_payload") else json.loads(dora.payload if hasattr(dora, "payload") else "{}")
            dora_tier = payload.get("tier", "")
        except Exception:
            pass

    flow_result = compute_flow_metrics(
        sprint_id=sprint.id,
        started_at_iso=sprint.started_at,
        completed_at_iso=completed,
        n_issues=1,
    )

    quality_score = 0.0
    quality = sprint.envelopes.get("quality", {})
    if isinstance(quality, dict):
        quality_score = quality.get("overall", 0.0)

    return TeamRunResult(
        team_name=team_name,
        sprint_id=sprint.id,
        started_at=sprint.started_at,
        completed_at=completed,
        status=sprint.status,
        rubric_score=rubric_score,
        dora_tier=dora_tier,
        flow_score=flow_result.flow_score,
        quality_score=quality_score,
        envelopes={
            "_replay": json.dumps({
                "team": team_name,
                "issue_id": issue.get("issue_id"),
            }),
        },
    )


def _compare_teams(a: TeamRunResult, b: TeamRunResult) -> tuple[str, float, float]:
    score_delta = (a.rubric_score or 0.0) - (b.rubric_score or 0.0)
    flow_delta = a.flow_score - b.flow_score

    # Factor in quality if available
    if a.quality_score and b.quality_score:
        combined_a = (a.rubric_score or 0.5) * 0.5 + a.quality_score * 0.5
        combined_b = (b.rubric_score or 0.5) * 0.5 + b.quality_score * 0.5
        if abs(combined_a - combined_b) > 0.05:
            return (a.team_name if combined_a > combined_b else b.team_name,
                    round(score_delta, 3), round(flow_delta, 3))

    if score_delta > 0.05:
        return (a.team_name, round(score_delta, 3), round(flow_delta, 3))
    elif score_delta < -0.05:
        return (b.team_name, round(score_delta, 3), round(flow_delta, 3))
    return ("tie", round(score_delta, 3), round(flow_delta, 3))


def run_paired_benchmark(
    repo_path: Path,
    issue: dict,
    agents_dir_a: Path,
    agents_dir_b: Path,
    *,
    model: str | None = None,
    _offline: bool = False,
) -> PairedRunReport:
    sha = _freeze_sha(repo_path) if not _offline else "deadbeef"

    if _offline:
        import uuid
        uid = uuid.uuid4().hex[:8]
        started = datetime.now(timezone.utc).isoformat()
        a = TeamRunResult(
            team_name="topology-a", sprint_id=f"sprint-a-{uid}",
            started_at=started, completed_at=started, status="completed",
        )
        b = TeamRunResult(
            team_name="topology-b", sprint_id=f"sprint-b-{uid}",
            started_at=started, completed_at=started, status="completed",
        )
        pm = PMStore()
        pm.create_sprint(f"sprint-a-{uid}", "branch-a", issue, status="completed", started_at=started)
        pm.create_sprint(f"sprint-b-{uid}", "branch-b", issue, status="completed", started_at=started)
    else:
        # Point scrum_team to use the alternative agents directory
        import orgos.subagents.scrum_team as scrum_team
        original_root = scrum_team._AGENTS_ROOT

        a = _run_team_sprint(repo_path, issue, "topology-a", model=model,
                             mock_pr=True)
        scrum_team._AGENTS_ROOT = agents_dir_b
        b = _run_team_sprint(repo_path, issue, "topology-b", model=model,
                             mock_pr=True)
        scrum_team._AGENTS_ROOT = original_root

    winner, score_delta, flow_delta = _compare_teams(a, b)

    return PairedRunReport(
        issue_id=str(issue.get("issue_id", "")),
        repo_sha=sha,
        created_at=datetime.now(timezone.utc).isoformat(),
        team_a=a,
        team_b=b,
        winner=winner,
        score_delta=score_delta,
        flow_delta=flow_delta,
        summary=(
            f"{winner if winner != 'tie' else 'No winner'}: "
            f"rubric delta={score_delta:+.3f}, flow delta={flow_delta:+.3f}"
        ),
    )

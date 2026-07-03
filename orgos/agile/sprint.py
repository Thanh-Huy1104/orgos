"""Sprint engine — orchestrates one sprint end-to-end.

Phase 1 scope:
  - No real GitHub. `issue` is a dict supplied by the caller.
  - PR opening is mocked via MockPRTool.
  - Retro / DORA / topology phases are TODOs (lit up in Phases 2-4).

A sprint:
  1. Creates a git worktree under .sprints/<sprint_id>/.
  2. Spawns Sprint Lead orchestrator with PM + Engineer + QA + Release as
     subordinates.
  3. Collects every subordinate's envelope and the synthesis envelope.
  4. Runs the deterministic rubric on the EngineeringEnvelope -> GradeEnvelope
     (overrides the LLM's GradeEnvelope to ensure reproducibility).
  5. Records the Sprint dataclass to PMStore (see Task 1.8).
"""

from __future__ import annotations

import json
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from orgos.pm import PMStore
from orgos.spawn import TaskBrief, spawn
from orgos.spawn.engine import SpawnResult
from orgos.subagents import (
    engineer_role, product_manager_role, qa_validator_role,
    release_manager_role, sprint_lead_role,
)
from orgos.tools.bash import BashTool
from orgos.tools.mock_pr_tool import MockPRTool

from .envelopes import (
    BacklogEnvelope, BriefEnvelope, DoraEnvelope, EngineeringEnvelope,
    GradeEnvelope, ReleaseEnvelope,
)
from .intake import rank_backlog
from .rubric import grade as run_rubric


@dataclass
class Sprint:
    id: str
    started_at: str
    repo_path: Path
    worktree_path: Path
    branch: str
    picked_issue: dict
    envelopes: dict[str, Any] = field(default_factory=dict)
    status: str = "in_progress"  # in_progress | completed | needs_revision | failed
    spawn_result: SpawnResult | None = None


def _new_sprint_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return f"{stamp}-{uuid.uuid4().hex[:6]}"


def _snapshot_path(sprint_id: str, base_dir: Path | None = None) -> Path:
    base = base_dir or Path(".")
    return base / ".sprints" / sprint_id / "snapshot.json"


def write_snapshot(
    sprint: Sprint,
    *,
    backlog: list[dict] | None = None,
    heuristics: list[dict] | None = None,
) -> Path:
    p = _snapshot_path(sprint.id, base_dir=sprint.repo_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "sprint_id": sprint.id,
        "started_at": sprint.started_at,
        "branch": sprint.branch,
        "picked_issue": sprint.picked_issue,
        "backlog": backlog or [],
        "heuristics": heuristics or [],
    }, indent=2))
    return p


def read_snapshot(sprint_id: str, *, base_dir: Path | None = None) -> dict:
    return json.loads(_snapshot_path(sprint_id, base_dir=base_dir).read_text())


def _make_worktree(repo: Path, sprint_id: str, branch: str) -> Path:
    worktree_root = repo / ".sprints" / sprint_id
    worktree_root.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "worktree", "add", "-b", branch, str(worktree_root), "HEAD"],
        cwd=repo, check=True, capture_output=True,
    )
    return worktree_root


def _brief_for_team(issue: dict) -> TaskBrief:
    return TaskBrief(
        objective=(
            f"Ship issue {issue.get('issue_id', '?')}: {issue.get('title', '')}. "
            f"Coordinate PM -> Engineer -> QA -> Release. Each subordinate "
            f"emits its typed envelope; you synthesise the final HandoffEnvelope."
        ),
        expected_output="A synthesised final envelope describing the sprint outcome.",
        success_criteria=[
            "Each subordinate produced a typed envelope.",
            "The Release envelope contains a pr_url (or mock://pr/...).",
        ],
        inputs={"issue": json.dumps(issue)},
    )


def run_sprint(
    repo_path: Path,
    issue: dict,
    *,
    model: str | None = None,
    mock_pr: bool = True,
    run_budget_tokens: int = 400_000,
) -> Sprint:
    sprint_id = _new_sprint_id()
    started_at = datetime.now(timezone.utc).isoformat()
    branch = f"agile/{sprint_id}"
    worktree = _make_worktree(repo_path, sprint_id, branch)
    write_snapshot(
        Sprint(
            id=sprint_id,
            started_at=started_at,
            repo_path=repo_path,
            worktree_path=worktree,
            branch=branch,
            picked_issue=issue,
            envelopes={},
            status="in_progress",
        ),
        backlog=[],
        heuristics=[],
    )

    pm = product_manager_role(model=model)
    engineer = engineer_role(model=model, extra_tools=[BashTool(cwd=str(worktree))])
    qa = qa_validator_role(model=model)
    release = release_manager_role(
        model=model,
        extra_tools=[MockPRTool()] if mock_pr else [],
    )
    lead = sprint_lead_role(model=model)

    brief = _brief_for_team(issue)
    result = spawn(
        lead, brief,
        subordinates=[pm, engineer, qa, release],
        run_budget_tokens=run_budget_tokens,
    )

    envelopes: dict[str, Any] = {}
    for tout in result.tasks_output:
        env = getattr(tout, "pydantic", None) or getattr(tout, "raw", None)
        if isinstance(env, BriefEnvelope):
            envelopes["brief"] = env
        elif isinstance(env, EngineeringEnvelope):
            envelopes["engineering"] = env
        elif isinstance(env, ReleaseEnvelope):
            envelopes["release"] = env

    # Deterministic rubric over the EngineeringEnvelope (overrides any LLM grade).
    if "brief" in envelopes and "engineering" in envelopes:
        envelopes["grade"] = run_rubric(envelopes["brief"], envelopes["engineering"])

    status = "completed" if (
        envelopes.get("grade")
        and envelopes["grade"].success_criteria_met
        and "release" in envelopes
    ) else "needs_revision"

    pm_store = PMStore()
    pm_store.create_sprint(sprint_id, branch, issue, status="in_progress", started_at=started_at)
    for phase, env in envelopes.items():
        pm_store.record_sprint_envelope(sprint_id, phase, env.model_dump_json())
    pm_store.update_sprint_status(sprint_id, status)

    return Sprint(
        id=sprint_id,
        started_at=started_at,
        repo_path=repo_path,
        worktree_path=worktree,
        branch=branch,
        picked_issue=issue,
        envelopes=envelopes,
        status=status,
        spawn_result=result,
    )


def _fetch_open_issues() -> list[dict]:
    """Live fetch via GitHubListIssuesTool. Patchable in tests."""
    from orgos.tools.github_issue_tool import GitHubListIssuesTool
    raw = GitHubListIssuesTool()._run(labels=["agent-eligible"], state="open", limit=30)
    return json.loads(raw)


def _make_backlog_envelope(candidates: list[dict]) -> BacklogEnvelope:
    return BacklogEnvelope(
        role="intake",
        status="completed",
        summary=f"ranked {len(candidates)} candidates",
        success_criteria_met=True,
        requires_human_approval=False,
        payload=json.dumps({"candidates": candidates}),
    )


def run_nightly_sprint(
    repo_path: Path,
    *,
    model: str | None = None,
    mock_pr: bool = False,
    _offline: bool = False,
) -> Sprint:
    """Production entrypoint: pull issues, rank, pick, run sprint, persist."""
    issues = _fetch_open_issues()
    candidates = rank_backlog(issues, max_candidates=10)
    if not candidates:
        # No eligible work; record an empty sprint and exit.
        sprint_id = _new_sprint_id()
        return Sprint(
            id=sprint_id,
            started_at=datetime.now(timezone.utc).isoformat(),
            repo_path=repo_path,
            worktree_path=repo_path,
            branch="",
            picked_issue={},
            envelopes={"backlog": _make_backlog_envelope([])},
            status="needs_revision",
        )
    picked = candidates[0]
    if _offline:
        sprint_id = _new_sprint_id()
        return Sprint(
            id=sprint_id,
            started_at=datetime.now(timezone.utc).isoformat(),
            repo_path=repo_path,
            worktree_path=repo_path,
            branch=f"agile/{sprint_id}",
            picked_issue=picked,
            envelopes={"backlog": _make_backlog_envelope(candidates)},
            status="completed",
        )
    sprint = run_sprint(repo_path, picked, model=model, mock_pr=mock_pr)
    sprint.envelopes["backlog"] = _make_backlog_envelope(candidates)
    # Re-persist the backlog envelope (run_sprint already wrote the rest).
    from orgos.pm import PMStore
    _pm = PMStore()
    _pm.record_sprint_envelope(
        sprint.id, "backlog", sprint.envelopes["backlog"].model_dump_json()
    )

    # DORA snapshot + candidate heuristics
    from orgos.agile.dora import compute_dora
    from orgos.agile.dora_bridge import dora_to_heuristic_candidates
    from orgos.reflect import Reflector
    snapshot = compute_dora(_pm, window_days=14)
    _pm.record_dora_snapshot(snapshot)
    prior = _pm.list_dora_snapshots(limit=3)
    candidates_h = dora_to_heuristic_candidates(_pm, snapshot, prior=prior)
    _reflector = Reflector(domain="agile")
    for h in candidates_h:
        _reflector.store_candidate(h)
    dora_env = DoraEnvelope(
        role="dora",
        status="completed",
        summary=f"tier={snapshot['tier']}",
        success_criteria_met=True,
        requires_human_approval=False,
        payload=json.dumps(snapshot),
    )
    sprint.envelopes["dora"] = dora_env
    _pm.record_sprint_envelope(sprint.id, "dora", dora_env.model_dump_json())

    # Role attribution (every sprint)
    from orgos.agile.attribution import compute_attribution
    from orgos.agile.topology import propose_topology_mutations
    scores = compute_attribution(sprint)
    baseline = sprint.envelopes.get("grade")
    baseline_score = baseline.parsed_payload().get("rubric_score", 0.0) if baseline else 0.0
    for role, score in scores.items():
        _pm.record_role_attribution(
            sprint_id=sprint.id, role_name=role,
            score=score,
            rubric_baseline=baseline_score,
            rubric_ablated=max(baseline_score - score, 0.0),
        )

    # Topology check every 5 sprints
    all_sprints = _pm.list_sprints(limit=6)
    if len(all_sprints) % 5 == 0:
        from pathlib import Path as _P
        props = propose_topology_mutations(_pm, _P("config/org.yaml"), window_sprints=5)
        for p in props:
            _pm.create_adr(sprint.id, p.kind, p.before_yaml, p.after_yaml, p.rationale)

    return sprint

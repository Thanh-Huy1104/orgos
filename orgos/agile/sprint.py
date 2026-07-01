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
    BriefEnvelope, EngineeringEnvelope, GradeEnvelope, ReleaseEnvelope,
)
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
    pm_store.create_sprint(sprint_id, branch, issue, status="in_progress")
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

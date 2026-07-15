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
    architect_role, devsecops_role, engineer_role, po_role,
    product_manager_role, qa_validator_role, release_manager_role,
    scrum_master_role, sprint_lead_role, test_role,
)
from orgos.tools.bash import BashTool
from orgos.tools.mock_pr_tool import MockPRTool

from .envelopes import (
    BacklogEnvelope, BriefEnvelope, DoraEnvelope, EngineeringEnvelope,
    GradeEnvelope, PullEnvelope, ReadyEnvelope, RefinementEnvelope,
    ReleaseEnvelope,
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
    # Drop a per-worktree .git/info/exclude so orgos-owned scratch files
    # (snapshot.json, retro.md if we add it later) never get picked up by a
    # blanket `git add -A` in the Engineer's commit step. exclude is
    # local-only, so nothing here leaks to the branch or origin.
    exclude_path = worktree_root / ".git" / "info" / "exclude"
    if not exclude_path.exists():
        # git worktree puts .git as a file, not a dir; resolve to the actual
        # per-worktree git dir.
        gitfile = (worktree_root / ".git").read_text().strip()
        if gitfile.startswith("gitdir: "):
            gitdir = Path(gitfile[len("gitdir: "):])
            if not gitdir.is_absolute():
                gitdir = (worktree_root / gitdir).resolve()
            exclude_path = gitdir / "info" / "exclude"
    exclude_path.parent.mkdir(parents=True, exist_ok=True)
    with exclude_path.open("a") as f:
        f.write("\n# orgos scratch — do not commit\nsnapshot.json\n")
    return worktree_root


def _brief_for_team(issue: dict, worktree: Path, branch: str) -> TaskBrief:
    return TaskBrief(
        objective=(
            f"Ship issue {issue.get('issue_id', '?')}: {issue.get('title', '')}. "
            f"Coordinate PM -> Engineer -> QA -> Release. Each subordinate "
            f"emits its typed envelope; you synthesise the final HandoffEnvelope.\n\n"
            f"The Engineer's git worktree is at {worktree}. All shell commands "
            f"run there automatically — do NOT try to cd or search elsewhere. "
            f"The worktree is a fork of the current repo HEAD; the branch is "
            f"'{branch}'.\n\n"
            f"IMPORTANT — the Engineer MUST commit its final change to the "
            f"worktree branch before handing off. Run:\n"
            f"  git add -A && git -c user.name=orgos-engineer "
            f"-c user.email=engineer@orgos.local commit -m "
            f"'<one-line summary of the change>'\n"
            f"...as the LAST step of the engineering phase, after tests pass. "
            f"The EngineeringEnvelope's commit_sha field must contain the SHA "
            f"of that new commit. If the tests don't pass, do not commit; "
            f"report status=needs_revision instead."
        ),
        expected_output="A synthesised final envelope describing the sprint outcome.",
        success_criteria=[
            "Each subordinate produced a typed envelope.",
            "The Engineer committed to the worktree branch with a valid SHA.",
            "The Release envelope contains a pr_url (or mock://pr/...).",
        ],
        inputs={"issue": json.dumps(issue), "worktree_path": str(worktree),
                "branch": branch},
    )


# Envelope subclasses keyed by the phase name they represent.
_PHASE_TO_ENVELOPE: dict[str, type] = {
    "backlog": BacklogEnvelope,
    "brief": BriefEnvelope,
    "refinement": RefinementEnvelope,
    "ready": ReadyEnvelope,
    "pull": PullEnvelope,
    "engineering": EngineeringEnvelope,
    "grade": GradeEnvelope,
    "release": ReleaseEnvelope,
    "dora": DoraEnvelope,
}

# Substrings in the envelope's `role` field that map to a phase.
_ROLE_TO_PHASE: list[tuple[str, str]] = [
    ("product-manager", "brief"),
    ("product manager", "brief"),
    ("pm", "brief"),
    ("po", "brief"),
    ("product owner", "brief"),
    ("scrum master", "refinement"),
    ("sm", "refinement"),
    ("architect", "refinement"),
    ("test", "refinement"),
    ("devsecops", "refinement"),
    ("engineer", "engineering"),
    ("qa", "grade"),
    ("release", "release"),
    ("intake", "backlog"),
    ("dora", "dora"),
]


def _extract_json_objects(text: str) -> list[str]:
    """Pull ALL balanced JSON objects out of a mixed prose/markdown blob.

    The hierarchical manager task's output typically contains several
    envelopes embedded in prose — one per subordinate delegated to. Grab
    each `{...}` span whose braces balance; caller filters by shape.
    """
    import re
    out: list[str] = []
    # First, any ```json ... ``` fenced blocks — most reliable.
    for m in re.finditer(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL):
        out.append(m.group(1))
    # Then any bare balanced JSON objects. Skip fenced blocks we already grabbed.
    consumed_spans = [(text.find(s), text.find(s) + len(s)) for s in out if s in text]
    i = 0
    while i < len(text):
        ch = text[i]
        if ch != "{":
            i += 1
            continue
        # Skip if we're inside a span we already captured via fence match.
        if any(a <= i < b for a, b in consumed_spans):
            i += 1
            continue
        depth = 0
        in_str = False
        esc = False
        for j in range(i, len(text)):
            c = text[j]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
            elif c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    out.append(text[i : j + 1])
                    i = j + 1
                    break
        else:
            break
    return out


# Preserve the singular form for callers that just want the first hit.
def _extract_json_object(text: str) -> str | None:
    hits = _extract_json_objects(text)
    return hits[0] if hits else None


def _classify_by_role(role: str) -> str | None:
    """Map a role name from an envelope's `role` field to a phase name."""
    role_l = role.lower()
    for needle, phase in _ROLE_TO_PHASE:
        if needle in role_l:
            return phase
    return None


def _parse_task_envelope(raw_text: str) -> tuple[str, Any] | None:
    """Try to parse one task's raw output into a typed envelope.

    Returns (phase, envelope) if the raw text contains a JSON blob that
    validates against one of the phase envelope subclasses, else None.
    """
    if not raw_text:
        return None
    blob = _extract_json_object(raw_text)
    if not blob:
        return None
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    role = data.get("role", "") or ""
    phase = _classify_by_role(role)
    if phase is None:
        return None
    subclass = _PHASE_TO_ENVELOPE.get(phase)
    if subclass is None:
        return None
    try:
        return phase, subclass.model_validate(data)
    except Exception:
        return None


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
    # Lock BashTool to the worktree so the Engineer can't wander the disk.
    engineer = engineer_role(
        model=model,
        extra_tools=[BashTool(default_working_dir=str(worktree))],
    )
    # QA is validator-tier (read-only) — it can't run Bash. It reads the
    # EngineeringEnvelope's test_output + test_passed and applies the rubric.
    qa = qa_validator_role(model=model)
    release = release_manager_role(
        model=model,
        extra_tools=[MockPRTool()] if mock_pr else [],
    )
    lead = sprint_lead_role(model=model)

    brief = _brief_for_team(issue, worktree, branch)
    # In mock mode there is no human review loop, so we auto-approve the
    # MockPRTool gate. Real runs (mock_pr=False) still require the caller to
    # supply an approval_fn through the higher-level nightly loop.
    approval_fn = (lambda role, name, args: True) if mock_pr else None
    result = spawn(
        lead, brief,
        subordinates=[pm, engineer, qa, release],
        approval_fn=approval_fn,
        run_budget_tokens=run_budget_tokens,
    )

    envelopes: dict[str, Any] = {}
    # 1. If a task carries a typed pydantic HandoffEnvelope subclass, take it
    #    directly (fast path for tasks where output_pydantic is set).
    # 2. Otherwise scan the task's raw string for embedded envelope JSON.
    #    CrewAI's hierarchical process routes subordinate outputs back to
    #    the manager task as prose — the envelopes are still there but need
    #    to be dug out.
    for tout in result.tasks_output:
        pyd = getattr(tout, "pydantic", None)
        if isinstance(pyd, BriefEnvelope):
            envelopes.setdefault("brief", pyd)
        elif isinstance(pyd, EngineeringEnvelope):
            envelopes.setdefault("engineering", pyd)
        elif isinstance(pyd, ReleaseEnvelope):
            envelopes.setdefault("release", pyd)
        elif isinstance(pyd, GradeEnvelope):
            envelopes.setdefault("grade", pyd)

        raw = getattr(tout, "raw", "") or ""
        for blob in _extract_json_objects(raw):
            try:
                data = json.loads(blob)
            except json.JSONDecodeError:
                continue
            if not isinstance(data, dict):
                continue
            phase = _classify_by_role(data.get("role", "") or "")
            if phase is None:
                continue
            subclass = _PHASE_TO_ENVELOPE.get(phase)
            if subclass is None:
                continue
            try:
                envelopes.setdefault(phase, subclass.model_validate(data))
            except Exception:
                continue

    # Deterministic rubric over the EngineeringEnvelope always wins over any
    # LLM-produced GradeEnvelope, since the rubric is reproducible.
    if "brief" in envelopes and "engineering" in envelopes:
        envelopes["grade"] = run_rubric(envelopes["brief"], envelopes["engineering"])

    # The sprint-lead's synthesis envelope is always kept as the "summary"
    # phase so the dashboard has a top-level narrative even when the
    # subordinate parses fail.
    envelopes["summary"] = result.envelope

    status = "completed" if (
        result.envelope.status == "completed"
        or (envelopes.get("grade") and envelopes["grade"].success_criteria_met
            and "release" in envelopes)
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


    # ── Pull-based sprint (self-organizing, no orchestrator) ─────────────────────

_WIKI_MCP = None


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

    # Retro envelope (deterministic, no LLM)
    from .retro import build_retro_from_sprint
    retro_env = build_retro_from_sprint(sprint)
    sprint.envelopes["retro"] = retro_env
    _pm.record_sprint_envelope(sprint.id, "retro", retro_env.model_dump_json())

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

    # Topology check every 5 sprints (use real count, not a capped list)
    if _pm.count_sprints() % 5 == 0:
        from pathlib import Path as _P
        props = propose_topology_mutations(_pm, _P("config/org.yaml"), window_sprints=5)
        for p in props:
            _pm.create_adr(sprint.id, p.kind, p.before_yaml, p.after_yaml, p.rationale)

    return sprint


def _brief_for_scrum_team(issue: dict, worktree: Path, branch: str) -> TaskBrief:
    return TaskBrief(
        objective=(
            f"Complete this sprint on issue #{issue.get('issue_id', '?')}: "
            f"{issue.get('title', '')}\n\n"
            f"Issue description: {issue.get('body', '')}\n\n"
            f"You are the PO (Product Owner, orchestrator). Your subordinates are "
            f"SM, Architect, Test, DevSecOps, and Release. Delegate work to them "
            f"in order so each produces a HandoffEnvelope.\n\n"
            f"CRITICAL — TOOLS: You and subordinates have BashTool (shell commands) "
            f"and MockPRTool. THAT IS IT. No board/API/wiki tools exist. "
            f"BashTool runs in the worktree: {worktree}\n\n"
            f"CRITICAL — ENVELOPE FORMAT: Every agent MUST output valid JSON:\n"
            f'{{\n'
            f'  "role": "<your role name>",\n'
            f'  "status": "completed|needs_revision|blocked|failed",\n'
            f'  "summary": "<what was done>",\n'
            f'  "success_criteria_met": true|false,\n'
            f'  "requires_human_approval": false,\n'
            f'  "payload": {{... any data ...}}\n'
            f'}}\n'
            f"NO markdown wrappers, NO code fences, NO prose around the JSON. "
            f"Output ONLY the JSON object.\n\n"
            f"ROLES:\n"
            f"1. SM — assess sprint readiness, brief the workers\n"
            f"2. Architect — WRITE the implementation files in {worktree}, run tests, "
            f"commit with: git add -A && git -c user.name=orgos-worker "
            f"-c user.email=worker@orgos.local commit -m '...'\n"
            f"3. Test — RUN the acceptance tests, verify output\n"
            f"4. DevSecOps — verify the change is safe, no leaked keys\n"
            f"5. Release — record a mock PR via MockPRTool\n\n"
            f"WORKTREE: {worktree}, BRANCH: {branch}\n"
            f"Commit SHA goes in payload.commit_sha. Test output in payload.test_output. "
            f"Files touched in payload.files_touched. PR URL in payload.pr_url."
        ),
        expected_output=(
            "A HandoffEnvelope JSON object summarising the sprint. "
            "Each subordinate produced their own JSON envelope."
        ),
        success_criteria=[
            "Each subordinate produced a valid HandoffEnvelope JSON with role/status/summary.",
            "The workers committed to the worktree branch with a valid SHA.",
            "The Release envelope contains a pr_url.",
        ],
        inputs={"issue": json.dumps(issue), "worktree_path": str(worktree),
                "branch": branch},
    )


def run_scrum_sprint(
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

    po = po_role(model=model)
    sm = scrum_master_role(model=model)
    arch = architect_role(
        model=model,
        extra_tools=[BashTool(default_working_dir=str(worktree))],
    )
    tst = test_role(
        model=model,
        extra_tools=[BashTool(default_working_dir=str(worktree))],
    )
    ds = devsecops_role(
        model=model,
        extra_tools=[BashTool(default_working_dir=str(worktree))],
    )
    release = release_manager_role(
        model=model,
        extra_tools=[MockPRTool()] if mock_pr else [],
    )

    brief = _brief_for_scrum_team(issue, worktree, branch)
    approval_fn = (lambda role, name, args: True) if mock_pr else None
    result = spawn(
        po, brief,
        subordinates=[sm, arch, tst, ds, release],
        approval_fn=approval_fn,
        run_budget_tokens=run_budget_tokens,
    )

    envelopes: dict[str, Any] = {}
    for tout in result.tasks_output:
        pyd = getattr(tout, "pydantic", None)
        if isinstance(pyd, (BriefEnvelope, EngineeringEnvelope, ReleaseEnvelope,
                           GradeEnvelope, RefinementEnvelope, ReadyEnvelope,
                           PullEnvelope)):
            phase_map = {
                BriefEnvelope: "brief", EngineeringEnvelope: "engineering",
                ReleaseEnvelope: "release", GradeEnvelope: "grade",
                RefinementEnvelope: "refinement", ReadyEnvelope: "ready",
                PullEnvelope: "pull",
            }
            for cls, phase in phase_map.items():
                if isinstance(pyd, cls):
                    envelopes.setdefault(phase, pyd)
                    break

        raw = getattr(tout, "raw", "") or ""
        for blob in _extract_json_objects(raw):
            try:
                data = json.loads(blob)
            except json.JSONDecodeError:
                continue
            if not isinstance(data, dict):
                continue
            phase = _classify_by_role(data.get("role", "") or "")
            if phase is None:
                continue
            subclass = _PHASE_TO_ENVELOPE.get(phase)
            if subclass is None:
                continue
            try:
                envelopes.setdefault(phase, subclass.model_validate(data))
            except Exception:
                continue

    if "brief" in envelopes and "engineering" in envelopes:
        envelopes["grade"] = run_rubric(envelopes["brief"], envelopes["engineering"])

    envelopes["summary"] = result.envelope

    status = "completed" if (
        result.envelope.status == "completed"
        or (envelopes.get("grade") and envelopes["grade"].success_criteria_met
            and "release" in envelopes)
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



# ------------------ Pull-based sprint (self-organizing, no orchestrator) --------------------

def _brief_for_pull_worker(issue: dict, worktree: Path, branch: str,
                           role_name: str, role_task: str) -> TaskBrief:
    return TaskBrief(
        objective=(
            f"You operate in a git worktree. BashTool runs there. Use bare paths.\n\n"
            f"FILE TO MODIFY: {issue.get('body', '')}\n"
            f"TASK: {issue.get('title', '')}\n\n"
            f"EXACT SEQUENCE:\n"
            f"1. Read the target file: type orgos\\agile\\thefile.py\n"
            f"2. Modify it: echo ... > orgos\\agile\\thefile.py\n"
            f"3. Run tests: pytest tests/agile/test_thefile.py -v\n"
            f"4. Commit: git add -A && git -c user.name=o -c user.email=o@o commit -m msg\n"
            f"5. Get SHA: git rev-parse HEAD\n"
            f"6. Output JSON envelope with commit_sha, files_touched, test_output, test_passed\n\n"
            f"OUTPUT ONLY JSON. NO markdown."
        ),
        expected_output=f"A HandoffEnvelope JSON from {role_name}.",
        success_criteria=[f"{role_name} completed their role task."],
        inputs={"issue": json.dumps(issue), "worktree_path": str(worktree),
                "branch": branch},
    )


_WIKI_MCP = None


def _get_wiki_mcp():
    global _WIKI_MCP
    if _WIKI_MCP is None:
        from orgos.mcps.wiki import create_wiki_mcp
        _WIKI_MCP = create_wiki_mcp()
    return _WIKI_MCP


def run_pull_sprint(
    repo_path: Path,
    issue: dict,
    *,
    model: str | None = None,
    mock_pr: bool = True,
    run_budget_tokens: int = 1_500_000,
) -> Sprint:
    sprint_id = _new_sprint_id()
    started_at = datetime.now(timezone.utc).isoformat()
    branch = f"agile/{sprint_id}"
    worktree = _make_worktree(repo_path, sprint_id, branch)
    repo = Path(repo_path)
    write_snapshot(Sprint(id=sprint_id, started_at=started_at, repo_path=repo,
                 worktree_path=worktree, branch=branch, picked_issue=issue,
                 envelopes={}, status="in_progress"), backlog=[], heuristics=[])

    envelopes: dict[str, Any] = {}

    # PO prioritizes - does NOT delegate
    po = po_role(model=model)
    po_brief = TaskBrief(
        objective=f"Prioritize issue #{issue.get('issue_id','?')} as READY. Do NOT delegate. Workers self-assign. Output JSON envelope.",
        expected_output="A HandoffEnvelope JSON.",
        success_criteria=["Issue prioritized as READY."],
    )
    po_result = spawn(po, po_brief, run_budget_tokens=min(run_budget_tokens // 4, 200_000))
    for tout in po_result.tasks_output:
        raw = getattr(tout, "raw", "") or ""
        for blob in _extract_json_objects(raw):
            try: data = json.loads(blob)
            except json.JSONDecodeError: continue
            if isinstance(data, dict) and data.get("role"):
                envelopes.setdefault("brief", data)

    # Workers spawn independently
    wiki = _get_wiki_mcp()
    wb = run_budget_tokens // 3
    arch = architect_role(model, extra_tools=[BashTool(default_working_dir=str(worktree))])
    arch.mcp_servers = [wiki]
    tst = test_role(model, extra_tools=[BashTool(default_working_dir=str(worktree))])
    tst.mcp_servers = [wiki]
    ds = devsecops_role(model, extra_tools=[BashTool(default_working_dir=str(worktree))])
    ds.mcp_servers = [wiki]

    workers = [
        ("architect", arch, "Write implementation files, run tests, git commit."),
        ("test", tst, "Run acceptance tests, verify output, report results."),
        ("devsecops", ds, "Verify no secrets, change is safe, diff is clean."),
    ]
    for role_name, role, role_task in workers:
        brief = _brief_for_pull_worker(issue, worktree, branch, role_name, role_task)
        wr = spawn(role, brief, run_budget_tokens=wb)
        for tout in wr.tasks_output:
            raw = getattr(tout, "raw", "") or ""
            for blob in _extract_json_objects(raw):
                try: data = json.loads(blob)
                except json.JSONDecodeError: continue
                if isinstance(data, dict) and data.get("role"):
                    envelopes.setdefault(role_name, data)

    # Release
    release = release_manager_role(model=model, extra_tools=[MockPRTool()] if mock_pr else [])
    rel_brief = TaskBrief(
        objective=f"Record mock PR for issue #{issue.get('issue_id')}. Use MockPRTool. Output JSON.",
        expected_output="A HandoffEnvelope JSON.",
        success_criteria=["pr_url is present."],
    )
    af = (lambda r, n, a: True) if mock_pr else None
    rel_result = spawn(release, rel_brief, approval_fn=af, run_budget_tokens=50_000)
    for tout in rel_result.tasks_output:
        raw = getattr(tout, "raw", "") or ""
        for blob in _extract_json_objects(raw):
            try: data = json.loads(blob)
            except json.JSONDecodeError: continue
            if isinstance(data, dict) and data.get("role") == "release-manager":
                envelopes.setdefault("release", data)

    envelopes["summary"] = envelopes.get("brief") or envelopes.get("architect") or {}
    status = "completed" if len(envelopes) >= 3 else "needs_revision"

    # Quality evaluation (deterministic + LLM)
    try:
        from orgos.agile.evaluator import QualityEvaluator
        evaluator = QualityEvaluator(model=model)
        sprint_stub = Sprint(id=sprint_id, started_at=started_at, repo_path=repo,
                             worktree_path=worktree, branch=branch, picked_issue=issue,
                             envelopes=envelopes, status=status, spawn_result=po_result)
        quality = evaluator.evaluate(sprint_stub, issue)
        envelopes["quality"] = {
            "overall": quality.overall,
            "deterministic": quality.deterministic_criteria,
            "llm_scores": quality.llm_scores,
            "llm_summary": quality.llm_summary,
        }
    except Exception:
        pass

    pm_store = PMStore()
    pm_store.create_sprint(sprint_id, branch, issue, status="in_progress", started_at=started_at)
    for phase, env in envelopes.items():
        if isinstance(env, dict):
            pm_store.record_sprint_envelope(sprint_id, phase, json.dumps(env))
    pm_store.update_sprint_status(sprint_id, status)

    return Sprint(id=sprint_id, started_at=started_at, repo_path=repo,
                  worktree_path=worktree, branch=branch, picked_issue=issue,
                  envelopes=envelopes, status=status, spawn_result=po_result)

"""orgos API server — REST backend for the Next.js dashboard.
 
Serves OrgMemory + PMStore data as JSON. Run alongside the scheduler:
 
    pip install fastapi uvicorn
    python -m uvicorn orgos.api:app --host 0.0.0.0 --port 8420
 
Endpoints:
    GET  /api/dashboard               — org overview
    GET  /api/departments             — department list with metrics
    GET  /api/departments/{name}/runs — run history
    GET  /api/projects                — all projects
    GET  /api/projects/{id}           — project detail + tasks
    GET  /api/proposals               — legacy: pending credential/tool requests
    POST /api/credentials/{i}/resolve — mark credential request resolved
    GET  /api/evolve/proposals        — evolution proposals (pending/approved/denied)
    POST /api/evolve/analyze          — trigger OrgAnalyzer (basic or deep)
    POST /api/evolve/proposals/{id}/approve — approve + apply a proposal
    POST /api/evolve/proposals/{id}/deny    — deny a proposal
    GET  /api/logs                    — recent run logs
    GET  /api/credentials             — pending credential requests
    GET  /api/tools                   — pending tool requests
    GET  /health                      — health check
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_here = Path(__file__).resolve().parent.parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

from contextlib import asynccontextmanager
from typing import Any

import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from orgos import OrgMemory, PMStore
from orgos.memory import OwnerProfile
from orgos.departments import Org, Department, NotificationConfig, run_department, spawn_project
from orgos.evolve import OrgAnalyzer, ProposalStore
from orgos.spawn import TaskBrief

# ── Config ──────────────────────────────────────────────────────────────────

# NOTE: ORG_YAML is intentionally NOT captured at module import time so that
# tests can override ORGOS_ORG_YAML via monkeypatch/setenv before the first call.
# Use _org_yaml_path() wherever you need the path — never a module-level constant.
MEMORY_DB = os.environ.get("ORGOS_MEMORY_DB", "./_orgos_memory/memory.db")
PM_DB = os.environ.get("ORGOS_PM_DB", "./_orgos_memory/pm.db")


def _org_yaml_path() -> str:
    """Return the org.yaml path, resolved fresh from the environment each call."""
    return os.environ.get("ORGOS_ORG_YAML", "./config/org.yaml")

memory: OrgMemory | None = None
pm: PMStore | None = None
org: Any = None
proposal_store: ProposalStore | None = None


def load_org():
    data = yaml.safe_load(Path(_org_yaml_path()).read_text())
    org_data = data.get("org", {})
    org_data["departments"] = data.get("departments", [])
    org_data["handoffs"] = data.get("handoffs", [])
    return Org.model_validate(org_data) if org_data else Org(name="Default")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global memory, pm, org, proposal_store
    memory = OrgMemory(MEMORY_DB)
    pm = PMStore(PM_DB)
    org = load_org()
    if org:
        org.memory = memory
    proposal_store = ProposalStore()
    yield
    if memory:
        memory.close()
    if pm:
        pm.close()
    if proposal_store:
        proposal_store.close()


app = FastAPI(title="orgos API", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ── Helpers ─────────────────────────────────────────────────────────────────

def _dept_metrics(name: str) -> dict:
    spend_7 = memory.department_spend(name, days=7)
    spend_30 = memory.department_spend(name, days=30)
    recent = memory.recent_runs(department=name, limit=20)
    completed = sum(1 for r in recent if r.status == "completed")
    return {
        "name": name,
        "spend_7d": spend_7["total_tokens"],
        "spend_30d": spend_30["total_tokens"],
        "runs_7d": spend_7["runs"],
        "recent_runs": len(recent),
        "success_rate": round(completed / max(len(recent), 1) * 100, 1),
        "failures": sum(1 for r in recent if r.status not in ("completed",)),
    }


# ── Routes ──────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "org": org.name if org else "not loaded"}


@app.get("/api/dashboard")
def dashboard():
    depts = [_dept_metrics(d.name) for d in org.departments] if org else []
    total_spend = sum(d["spend_30d"] for d in depts)
    total_runs = sum(d["recent_runs"] for d in depts)
    recent = memory.recent_runs(limit=10)
    projects = pm.list_projects(limit=10)

    return {
        "org_name": org.name if org else "default",
        "departments": depts,
        "total_spend_30d": total_spend,
        "total_runs_30d": total_runs,
        "budget": org.default_max_budget_tokens if org else None,
        "projects": [
            {"id": p.id, "name": p.name, "status": p.status, "goal": p.goal[:200]}
            for p in projects
        ],
        "recent_activity": [
            {
                "id": r.id, "department": r.department, "role": r.role,
                "status": r.status, "summary": r.summary[:200],
                "tokens": r.total_tokens, "created_at": r.created_at,
            }
            for r in recent
        ],
    }


@app.get("/api/departments")
def departments():
    if not org:
        return []
    return [_dept_metrics(d.name) for d in org.departments]


@app.get("/api/org")
def org_detail():
    """Return org structure with live per-department metrics."""
    if not org:
        return {"error": "Org not loaded"}
    result = {
        "name": org.name,
        "default_model": org.default_model,
        "departments": []
    }
    for d in org.departments:
        dept = {
            "name": d.name,
            "description": d.description,
            "supervisor": None,
            "members": [],
            "sops": [{"name": s.name, "cadence": s.cadence, "objective": s.brief.objective[:200]} for s in d.sops],
            "shared_mcps": [m.get("type", str(type(m).__name__)) if isinstance(m, dict) else str(type(m).__name__) for m in d.shared_mcps],
            "metrics": _dept_metrics(d.name),
        }
        dept["metrics"]["recent_runs"] = [
            {
                "id": r.id, "role": r.role, "status": r.status,
                "summary": r.summary[:200], "tokens": r.total_tokens,
                "created_at": r.created_at,
            }
            for r in memory.recent_runs(department=d.name, limit=5)
        ]
        for r in d.all_roles():
            enriched = d._enrich_role(r)
            role_info = {
                "name": r.name,
                "tier": r.tier.value,
                "model": r.model,
                "system_prompt": r.system_prompt[:500],
                "tools": [getattr(t, "name", t.__class__.__name__) for t in enriched.tools],
                "mcps": [
                    _mcp_label(m) for m in enriched.mcp_servers
                ],
                "skills": enriched.skills,
            }
            if r.name == d.supervisor.name:
                dept["supervisor"] = role_info
            else:
                dept["members"].append(role_info)
        result["departments"].append(dept)
    return result


@app.get("/api/departments/{name}/runs")
def department_runs(name: str, limit: int = 50):
    runs = memory.recent_runs(department=name, limit=limit)
    return [
        {
            "id": r.id, "department": r.department, "role": r.role,
            "status": r.status, "objective": r.objective[:300],
            "summary": r.summary[:500], "total_tokens": r.total_tokens,
            "success_criteria_met": r.success_criteria_met,
            "created_at": r.created_at,
        }
        for r in runs
    ]


@app.get("/api/projects")
def projects(status: str | None = None):
    projs = pm.list_projects(status=status, limit=50)
    return [
        {
            "id": p.id, "name": p.name, "status": p.status,
            "goal": p.goal[:300], "owner": p.owner,
            "task_count": len(json.loads(p.task_ids)),
            "created_at": p.created_at, "updated_at": p.updated_at,
        }
        for p in projs
    ]


@app.get("/api/projects/{project_id}")
def project_detail(project_id: str):
    progress = pm.get_project_progress(project_id)
    if "error" in progress:
        raise HTTPException(404, progress["error"])
    return progress


@app.get("/api/proposals")
def proposals():
    path = Path(_org_yaml_path())
    if not path.exists():
        return {"proposals": [], "credential_requests": [], "tool_requests": []}

    data = yaml.safe_load(path.read_text())
    return {
        "credential_requests": data.get("pending_credential_requests", []),
        "tool_requests": data.get("pending_tool_requests", []),
        "policy_changes": data.get("pending_policy_changes", []),
    }


@app.get("/api/credentials")
def credentials():
    path = Path(_org_yaml_path())
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text())
    return data.get("pending_credential_requests", [])


@app.get("/api/tools")
def tools():
    path = Path(_org_yaml_path())
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text())
    return data.get("pending_tool_requests", [])


@app.get("/api/logs")
def logs(limit: int = 100, department: str | None = None):
    runs = memory.recent_runs(department=department, limit=limit) if department else memory.recent_runs(limit=limit)
    return [
        {
            "id": r.id, "department": r.department, "role": r.role,
            "status": r.status, "summary": r.summary[:300],
            "objective": r.objective[:200], "tokens": r.total_tokens,
            "created_at": r.created_at,
        }
        for r in runs
    ]


@app.get("/api/policies")
def get_policies(category: str | None = None):
    """List all policies in the policy bank. Optional category filter."""
    path = Path("config/policy-bank.yaml")
    if not path.exists():
        return {"policies": []}
    data = yaml.safe_load(path.read_text())
    policies = data.get("policies", [])
    if category:
        policies = [p for p in policies if category in (p.get("categories", []) or [p.get("category", "")])]
    # Collect all unique categories
    all_cats = set()
    for p in data.get("policies", []):
        cats = p.get("categories", []) or [p.get("category", "")]
        all_cats.update(cats)
    return {"policies": policies, "categories": sorted(all_cats)}


class AddPolicyBody(BaseModel):
    id: str
    title: str
    categories: list[str] = ["governance"]
    severity: str = "medium"
    rule: str
    references: list[str] = []


@app.post("/api/policies")
def add_policy(body: AddPolicyBody):
    """Add a new policy to the policy bank."""
    path = Path("config/policy-bank.yaml")
    if not path.exists():
        data = {"policies": []}
    else:
        data = yaml.safe_load(path.read_text())
    policies = data.get("policies", [])
    if any(p.get("id") == body.id for p in policies):
        raise HTTPException(400, f"Policy {body.id} already exists")
    entry = body.model_dump()
    policies.append(entry)
    data["policies"] = policies
    path.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False, width=120))
    return {"added": body.id, "total": len(policies)}


@app.delete("/api/policies/{policy_id}")
def delete_policy(policy_id: str):
    """Remove a policy from the bank."""
    path = Path("config/policy-bank.yaml")
    if not path.exists():
        raise HTTPException(404, "Policy bank not found")
    data = yaml.safe_load(path.read_text())
    before = len(data.get("policies", []))
    data["policies"] = [p for p in data.get("policies", []) if p.get("id") != policy_id]
    if len(data["policies"]) == before:
        raise HTTPException(404, f"Policy {policy_id} not found")
    path.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False, width=120))
    return {"deleted": policy_id, "remaining": len(data["policies"])}
@app.get("/api/research")
def research_reports(limit: int = 20):
    """List recent research reports."""
    return pm.list_research_reports(limit=limit)


@app.get("/api/research/{report_id}")
def research_report_detail(report_id: str):
    """Get a single research report with full content."""
    r = pm.get_research_report(report_id)
    if not r:
        raise HTTPException(404, "Report not found")
    return r
@app.get("/api/scheduler")
def scheduler_status():
    jobs = []
    for d in org.departments if org else []:
        for s in d.sops:
            if s.cadence:
                key = f"sched_last:{d.name}:{s.name}"
                last = memory.get_preference(key)
                jobs.append({
                    "department": d.name, "sop": s.name,
                    "cadence": s.cadence, "last_run": last,
                })
    return {"jobs": jobs, "total": len(jobs)}


# ── Interactive actions ───────────────────────────────────────────────────

@app.post("/api/scheduler/run-pending")
def trigger_scheduler():
    """Run all pending scheduled jobs now."""
    from orgos.scheduler import Scheduler
    sched = Scheduler(org)
    results = sched.run_pending()
    return {"ran": len(results), "results": results}


@app.post("/api/departments/{name}/run")
def trigger_department(name: str):
    """Trigger a department run with a custom objective."""
    dept = org.find_department(name) if org else None
    if not dept:
        raise HTTPException(404, f"Department {name} not found")
    # Run the first SOP or a generic brief
    sop = dept.sops[0] if dept.sops else None
    brief = sop.brief if sop else TaskBrief(objective=f"Run {name} department check-in.")
    result = run_department(org, name, brief, verbose=False, record=True)
    return {
        "department": name,
        "status": result.envelope.status,
        "summary": result.envelope.summary[:500],
        "tokens": result.token_usage,
    }


class CreateProjectBody(BaseModel):
    goal: str
    name: str | None = None


def _classify_prompt(goal: str, org: Any) -> str:
    """Classify a prompt as 'simple' or 'complex'.

    Simple: single department, one step, query-style ("what's on...", "check...",
    "show me...").  These go direct to the best department.
    Complex: multi-step, multi-department, project-style ("scan X and generate
    report and schedule Y").  These get full project decomposition.
    """
    goal_lower = goal.lower()

    # Simple patterns — single action, query-style
    simple_patterns = [
        "what's on", "what is on", "check my", "show me", "list my",
        "what do i have", "what are my", "tell me about",
        "when is", "who is", "where is",
    ]
    # Complex patterns — multiple actions, project-style
    complex_patterns = [
        " and ", " then ", " also ", "generate a report", "create a report",
        "scan", "analyze and", "deploy", "build", "implement",
        "set up", "configure", "train", "migrate",
    ]

    is_simple = any(p in goal_lower for p in simple_patterns)
    is_complex = any(p in goal_lower for p in complex_patterns)

    if is_complex:
        return "complex"
    if is_simple:
        return "simple"

    # Default: if it's short (one sentence), treat as simple
    sentences = [s.strip() for s in goal.replace("?", ".").replace("!", ".").split(".") if s.strip()]
    if len(sentences) <= 1 and len(goal) < 150:
        return "simple"

    return "complex"


def _mcp_label(mcp: Any) -> str:
    """Human-readable label for an MCP server config."""
    args = getattr(mcp, "args", [])
    if isinstance(args, list):
        if "internet_mcp" in str(args):
            return "internet (web_search, web_fetch)"
        if "pm_mcp" in str(args):
            return "pm (git, tasks, tests)"
        if "gcal_mcp" in str(args):
            return "gcal (Google Calendar)"
        if "memory_mcp" in str(args):
            return "memory (run history)"
    return "mcp"


def _route_simple(goal: str, org: Any) -> dict:
    """Handle a simple prompt by spawning the best agent directly.

    Skips department delegation — just spawns a single enriched agent.
    """
    from orgos.spawn import TaskBrief
    from orgos.spawn import spawn

    # Pick the best department for the goal. The desk runs three on-mission
    # departments — quant (discovery), compliance (review), research (the
    # general-purpose investigator and default).
    goal_lower = goal.lower()
    if any(kw in goal_lower for kw in ("scan", "pair", "cointegration", "trade", "stock", "etf", "quant")):
        dept_name = "quant"
    elif any(kw in goal_lower for kw in ("compliance", "policy", "legal", "review", "regulat")):
        dept_name = "compliance"
    else:
        dept_name = "research"

    dept = org.find_department(dept_name) or (org.departments[0] if org.departments else None)
    if not dept:
        raise HTTPException(503, "No departments configured")

    # Spawn the best-equipped member directly (skip orchestrator delegation)
    # For simple queries, a worker with tools is more efficient than an
    # orchestrator delegating to a worker.
    agent = None
    for member in dept.members:
        enriched = dept._enrich_role(member)
        if enriched.tools:
            agent = enriched
            break
    if agent is None:
        agent = dept.supervisor

    result = spawn(agent, TaskBrief(objective=goal), verbose=False)

    # Record in memory
    org.use_memory().record_run(
        department=dept_name, role=agent.name,
        envelope=result.envelope, brief=TaskBrief(objective=goal),
        token_usage=result.token_usage, org=org.name,
    )

    return {
        "mode": "simple",
        "department": dept_name,
        "status": result.envelope.status,
        "summary": result.envelope.summary[:1000],
        "tokens": result.token_usage,
    }


@app.post("/api/projects")
def create_project(body: CreateProjectBody):
    """Create a project or handle a simple query directly.

    Simple queries ("what's on my calendar?") go direct to the best
    department. Complex queries get full project decomposition.
    """
    mode = _classify_prompt(body.goal, org)

    if mode == "simple":
        return _route_simple(body.goal, org)

    # Complex: full project decomposition
    result = spawn_project(org, body.goal, project_name=body.name, verbose=False)
    if "error" in result:
        raise HTTPException(400, result["error"])
    return {
        "mode": "complex",
        "project_id": result["project_id"],
        "project_name": result["project_name"],
        "tasks": len(result["tasks"]),
        "tasks_detail": result["tasks"],
    }

@app.post("/api/projects/{project_id}/dispatch")
def dispatch_project(project_id: str):
    """Dispatch all pending tasks for a project to their departments."""
    progress = pm.get_project_progress(project_id)
    if "error" in progress:
        raise HTTPException(404, progress["error"])

    dispatched = []
    for task in progress.get("tasks", []):
        if task["status"] == "done":
            continue
        dept_name = task.get("department") or ""
        if not dept_name or dept_name == "?":
            # Assign to first available department
            dept_name = org.departments[0].name if org and org.departments else ""
        if not dept_name:
            dispatched.append({"task": task["title"], "status": "no_department"})
            continue
        dept = org.find_department(dept_name) if org else None
        if not dept:
            dispatched.append({"task": task["title"], "department": dept_name, "status": "no_department"})
        try:
            brief = TaskBrief(objective=task["title"])
            result = run_department(org, task.get("department", ""), brief, verbose=False, record=True)
            status = result.envelope.status
            pm.update_task(task["id"], "done" if status == "completed" else "blocked", notes=result.envelope.summary[:200])
            dispatched.append({"task": task["title"], "department": task.get("department"), "status": status})
        except Exception as e:
            dispatched.append({"task": task["title"], "status": f"error: {e}"})

    pm.update_project_status(project_id, "completed" if all(d["status"] == "completed" for d in dispatched) else "active")

    # Synthesize final report if all tasks are done and no report exists yet
    progress_after = pm.get_project_progress(project_id)
    remaining = [t for t in progress_after.get("tasks", []) if t["status"] not in ("done",)]
    if not remaining and not progress_after.get("final_report"):
        _synthesize_report(project_id, progress_after, dispatched)

    return {"project_id": project_id, "dispatched": len(dispatched), "results": dispatched}


def _synthesize_report(project_id: str, progress: dict, results: list) -> None:
    """Spawn a synthesis agent to produce a consolidated project report."""
    from orgos.spawn import RoleSpec, TaskBrief, PermissionTier
    from orgos.spawn import spawn
    import json

    task_summaries = "\n".join(
        f"- [{t['status']}] {t.get('department', '?')}: {t['title']}\n  {t.get('description', '')[:300]}"
        for t in progress.get("tasks", [])
    )

    synth = RoleSpec(
        name="report-synthesizer",
        tier=PermissionTier.WORKER,
        system_prompt=(
            "You synthesize project results into a clear executive summary. "
            "Read all task outputs and produce a structured final report with: "
            "key findings, decisions made, blocked items, and next steps. "
            "Be concise and actionable."
        ),
        model=org.default_model if org else "gpt-4o-mini",
        max_iter=10,
    )

    brief = TaskBrief(
        objective=(
            f"Synthesize these project task results into a final report:\n\n"
            f"**Project**: {progress.get('project_name', 'Unknown')}\n"
            f"**Goal**: {progress.get('goal', '')}\n\n"
            f"**Task outputs**:\n{task_summaries}\n\n"
            "Produce a markdown report with: Summary, Key Findings, Blocked Issues, Next Steps."
        ),
        expected_output="A concise markdown report synthesizing all task results.",
    )

    try:
        result = spawn(synth, brief, verbose=False)
        report = result.envelope.summary
        pm.set_project_report(project_id, report)
        pm.update_project_status(project_id, "completed" if result.envelope.status == "completed" else "active")
    except Exception:
        pass


@app.post("/api/credentials/{index}/resolve")
def resolve_credential(index: int):
    """Mark a credential request as resolved (owner provided the key)."""
    path = Path(_org_yaml_path())
    if not path.exists():
        raise HTTPException(404, "org.yaml not found")
    data = yaml.safe_load(path.read_text())
    creds = data.get("pending_credential_requests", [])
    if index < 0 or index >= len(creds):
        raise HTTPException(404, "Invalid index")
    resolved = creds.pop(index)
    data["pending_credential_requests"] = creds
    resolved_list = data.get("resolved_credentials", [])
    resolved_list.append(resolved)
    data["resolved_credentials"] = resolved_list
    path.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False, width=120))
    return {"resolved": resolved.get("department", "unknown"), "remaining": len(creds)}


# ── Evolve (self-improving org) ────────────────────────────────────────────


class AnalyzeBody(BaseModel):
    mode: str = "basic"  # "basic" or "deep"


@app.post("/api/evolve/analyze")
def trigger_analysis(body: AnalyzeBody | None = None):
    """Trigger org analysis. mode=basic (deterministic, zero tokens) or mode=deep (LLM-powered)."""
    if not proposal_store or not org:
        raise HTTPException(503, "Org not loaded")
    mode = body.mode if body else "basic"
    analyzer = OrgAnalyzer(org)
    if mode == "deep":
        proposals = analyzer.deep_analysis(verbose=False)
    else:
        proposals = analyzer.basic_proposals()
    count = proposal_store.add_all(proposals)
    return {
        "mode": mode,
        "proposals_found": len(proposals),
        "proposals_stored": count,
        "proposal_ids": [p.id for p in proposals],
    }


@app.get("/api/evolve/proposals")
def evolve_proposals():
    """List all pending evolution proposals."""
    if not proposal_store:
        return {"proposals": []}
    return {"proposals": proposal_store.list_pending()}


@app.post("/api/evolve/proposals/{proposal_id}/approve")
def approve_proposal(proposal_id: str):
    """Approve a proposal and apply it to org.yaml."""
    if not proposal_store:
        raise HTTPException(503, "Proposal store not available")
    entry = proposal_store.get(proposal_id)
    if not entry:
        raise HTTPException(404, f"Proposal {proposal_id} not found")
    if entry["status"] != "pending":
        raise HTTPException(400, f"Proposal {proposal_id} is already {entry['status']}")

    from orgos.evolve import ProposalType, Proposal, apply_proposal
    ptype = ProposalType(entry["type"])
    proposal = Proposal(
        id=entry["id"], type=ptype, target=entry["target"],
        summary=entry["summary"], reasoning=entry["reasoning"],
        risk=entry["risk"], evidence=entry["evidence"],
        changes=entry["changes"],
        recommended_tools=entry["recommended_tools"],
        recommended_mcps=entry["recommended_mcps"],
        credential_needs=entry["credential_needs"],
        created_at=entry["created_at"],
    )
    result = apply_proposal(proposal, _org_yaml_path())
    if result.get("applied"):
        proposal_store.approve(proposal_id)
        global org
        org = load_org()
        if org:
            org.memory = memory
        return {"approved": True, "proposal_id": proposal_id, "message": result["message"]}
    return {"approved": False, "proposal_id": proposal_id, "message": result["message"]}


@app.post("/api/evolve/proposals/{proposal_id}/deny")
def deny_proposal(proposal_id: str):
    """Deny a proposal."""
    if not proposal_store:
        raise HTTPException(503, "Proposal store not available")
    entry = proposal_store.deny(proposal_id)
    if not entry:
        raise HTTPException(404, f"Proposal {proposal_id} not found")
    return {"denied": True, "proposal_id": proposal_id}


@app.get("/api/calendar")
def calendar():
    """Scheduler calendar with job history and next-run estimates."""
    jobs = []
    for d in org.departments if org else []:
        for s in d.sops:
            if not s.cadence:
                continue
            key = f"sched_last:{d.name}:{s.name}"
            last = memory.get_preference(key)
            recent = memory.recent_runs(department=d.name, limit=3)
            jobs.append({
                "department": d.name,
                "sop": s.name,
                "cadence": s.cadence,
                "last_run": last,
                "recent_runs": [
                    {"status": r.status, "tokens": r.total_tokens, "at": r.created_at}
                    for r in recent
                ],
            })
    return {"jobs": jobs}


@app.get("/api/dora")
def dora_endpoint(window: int = 14, limit: int = 90) -> dict:
    """Return latest DORA snapshot and history.

    Query params:
      window  — rolling window in days used when computing a live snapshot
                if no stored snapshot exists (default 14)
      limit   — max history rows to return (default 90)
    """
    from orgos.agile.dora import compute_dora as _compute_dora

    # Re-use the lifespan PMStore when available (populated in tests via env var).
    _pm = pm if pm is not None else PMStore(PM_DB)
    latest = _pm.latest_dora_snapshot()
    if latest is None:
        latest = _compute_dora(_pm, window_days=window)
    history = _pm.list_dora_snapshots(limit=limit)
    return {"latest": latest, "history": history}


@app.get("/api/heuristics")
def heuristics_endpoint() -> dict:
    """Return active and candidate heuristics from Reflector storage.

    active     — heuristics with use_count > 0 (have been retrieved before)
    candidates — heuristics with use_count = 0 (never retrieved yet)
    """
    from orgos.reflect import Reflector

    r = Reflector(domain="agile")
    active = r.list_active()
    candidates = r.list_candidates()
    return {
        "active": [h.__dict__ for h in active],
        "candidates": [h.__dict__ for h in candidates],
    }


# ── Team topology + ADR endpoints ─────────────────────────────────────────────

_ruamel_yaml = None


def _get_ruamel():
    global _ruamel_yaml
    if _ruamel_yaml is None:
        from ruamel.yaml import YAML
        _ruamel_yaml = YAML()
    return _ruamel_yaml


@app.get("/api/team/topology")
def team_topology() -> dict:
    """Return org topology (roles + edges) from config/org.yaml + latest attribution."""
    _pm = pm if pm is not None else PMStore(PM_DB)
    cfg_path = Path(_org_yaml_path())
    if not cfg_path.exists():
        return {"roles": [], "edges": []}
    cfg = _get_ruamel().load(cfg_path.read_text())
    depts = cfg.get("departments") or []
    if not depts:
        return {"roles": [], "edges": []}
    sup = depts[0].get("supervisor") or {}
    members = depts[0].get("members") or []
    roles = [{"name": sup.get("name", "supervisor"), "tier": "orchestrator", "contribution": 0.0}]
    for m in members:
        rows = _pm.list_role_attribution(m.get("name", ""), since_days=7)
        latest = rows[0]["score"] if rows else 0.0
        roles.append({
            "name": m.get("name", ""),
            "tier": m.get("tier", "worker"),
            "contribution": latest,
        })
    edges = [
        {"from": sup.get("name", "supervisor"), "to": r["name"], "weight": r["contribution"]}
        for r in roles[1:]
    ]
    return {"roles": roles, "edges": edges}


@app.get("/api/team/adrs")
def list_adrs() -> dict:
    """Return ADRs grouped by status: {pending, approved, applied, rejected}."""
    _pm = pm if pm is not None else PMStore(PM_DB)
    all_adrs = _pm.list_adrs()
    grouped: dict[str, list] = {"pending": [], "approved": [], "applied": [], "rejected": []}
    for a in all_adrs:
        grouped.setdefault(a["status"], []).append(a)
    return grouped


@app.post("/api/team/adrs/{adr_id}/approve")
def approve_adr(adr_id: int) -> dict:
    """Approve an ADR: set status=approved then apply it (writes config + marks applied)."""
    from orgos.evolve import apply_adr
    _pm = pm if pm is not None else PMStore(PM_DB)
    _pm.set_adr_status(adr_id, "approved")
    apply_adr(_pm, adr_id)
    return {"ok": True, "id": adr_id, "status": "applied"}


@app.post("/api/team/adrs/{adr_id}/reject")
def reject_adr(adr_id: int) -> dict:
    """Reject an ADR: set status=rejected."""
    _pm = pm if pm is not None else PMStore(PM_DB)
    _pm.set_adr_status(adr_id, "rejected")
    return {"ok": True, "id": adr_id, "status": "rejected"}


class ReplayReq(BaseModel):
    parent_sprint_id: str
    mutation_kind: str  # swap_backlog_pick | inject_heuristic | swap_role
    mutation_args: dict


@app.post("/api/lab/replay")
def lab_replay(req: ReplayReq) -> dict:
    from orgos.agile.mutations import (
        InjectHeuristic, SwapBacklogPick, SwapRole,
    )
    from orgos.agile.replay import replay_sprint

    if req.mutation_kind == "swap_backlog_pick":
        m = SwapBacklogPick(**req.mutation_args)
    elif req.mutation_kind == "inject_heuristic":
        m = InjectHeuristic(**req.mutation_args)
    elif req.mutation_kind == "swap_role":
        m = SwapRole(**req.mutation_args)
    elif req.mutation_kind == "swap_topology":
        from orgos.agile.mutations import SwapTopology
        m = SwapTopology(**req.mutation_args)
    else:
        return {"error": f"unknown mutation_kind: {req.mutation_kind}"}
    try:
        s = replay_sprint(req.parent_sprint_id, m)
    except Exception as exc:
        return {"error": str(exc)}
        return {"replay_sprint_id": s.id, "status": s.status,
             "picked_issue": s.picked_issue}


class PairedRunReq(BaseModel):
    issue_id: str = ""
    issue_title: str = ""
    agents_dir_b: str = ""


@app.post("/api/lab/paired-run")
def lab_paired_run(req: PairedRunReq) -> dict:
    """Run a dual-team paired benchmark on the same issue.

    Compares the default agents/ topology against an alternative
    agents/ directory specified by agents_dir_b.
    """
    from orgos.agile.paired_run import run_paired_benchmark

    issue = {"issue_id": req.issue_id, "title": req.issue_title}
    agents_dir_a = Path("agents")
    agents_dir_b = Path(req.agents_dir_b) if req.agents_dir_b else Path("agents_alt")

    try:
        report = run_paired_benchmark(
            repo_path=Path("."),
            issue=issue,
            agents_dir_a=agents_dir_a,
            agents_dir_b=agents_dir_b,
        )
        return {
            "issue_id": report.issue_id,
            "repo_sha": report.repo_sha,
            "winner": report.winner,
            "score_delta": report.score_delta,
            "flow_delta": report.flow_delta,
            "summary": report.summary,
            "team_a": {
                "sprint_id": report.team_a.sprint_id,
                "status": report.team_a.status,
                "rubric_score": report.team_a.rubric_score,
                "dora_tier": report.team_a.dora_tier,
                "flow_score": report.team_a.flow_score,
            },
            "team_b": {
                "sprint_id": report.team_b.sprint_id,
                "status": report.team_b.status,
                "rubric_score": report.team_b.rubric_score,
                "dora_tier": report.team_b.dora_tier,
                "flow_score": report.team_b.flow_score,
            },
        }
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/lab/flow-metrics/{sprint_id}")
def lab_flow_metrics(sprint_id: str) -> dict:
    """Compute flow-efficiency metrics for a single sprint."""
    _pm = pm if pm is not None else PMStore(PM_DB)
    row = _pm.get_sprint(sprint_id)
    if not row:
        raise HTTPException(404, "sprint not found")

    from orgos.agile.flow_metric import compute_flow_metrics
    result = compute_flow_metrics(
        sprint_id=sprint_id,
        started_at_iso=row["started_at"],
        completed_at_iso=row.get("updated_at"),
        n_issues=1,
    )
    return {
        "sprint_id": result.sprint_id,
        "duration_seconds": result.duration_seconds,
        "takt_time": result.takt_time,
        "velocity_delta": result.velocity_delta,
        "flow_score": result.flow_score,
        "warnings": result.warnings,
    }


@app.get("/api/sprints")
def list_sprints(limit: int = 50) -> list[dict]:
    """List sprints, most recent first. Consumed by the dashboard /sprints board
    and the /lab picker (which filters for completed sprints)."""
    _pm = pm if pm is not None else PMStore(PM_DB)
    rows = _pm.list_sprints(limit=limit)
    # Return the picked_issue as parsed JSON so the frontend renders the issue
    # id/title without another decode step.
    for r in rows:
        raw = r.get("picked_issue") or "{}"
        try:
            r["picked_issue"] = json.loads(raw) if isinstance(raw, str) else raw
        except json.JSONDecodeError:
            r["picked_issue"] = {}
    return rows


@app.get("/api/sprints/{sprint_id}")
def get_sprint(sprint_id: str) -> dict:
    _pm = pm if pm is not None else PMStore(PM_DB)
    row = _pm.get_sprint(sprint_id)
    if not row:
        return {"error": "not_found"}
    envs = json.loads(row.get("envelopes_json") or "{}")
    replay = envs.get("_replay")
    return {"sprint": row, "envelopes": envs, "replay": replay}


@app.get("/agent-card.json")
def agent_card() -> dict:
    return {
        "name": "orgos-engineering",
        "description": "A self-organizing agile engineering team that ships one issue per sprint.",
        "version": "0.1.0",
        "url": None,
        "capabilities": {"streaming": False, "pushNotifications": False},
        "skills": [
            {"id": "sprint-lead", "name": "Sprint Lead",
             "description": "Orchestrates a sprint: picks the issue, routes the team, synthesises the final handoff.",
             "inputModes": ["application/json"],
             "outputModes": ["application/json"]},
            {"id": "product-manager", "name": "Product Manager",
             "description": "Turns a GitHub issue into a TaskBrief with acceptance tests.",
             "inputModes": ["application/json"], "outputModes": ["application/json"]},
            {"id": "engineer", "name": "Engineer",
             "description": "Implements the change in a git worktree and runs the tests.",
             "inputModes": ["application/json"], "outputModes": ["application/json"]},
            {"id": "qa-validator", "name": "QA Validator",
             "description": "Grades the engineering handoff against the brief's acceptance tests.",
             "inputModes": ["application/json"], "outputModes": ["application/json"]},
            {"id": "release-manager", "name": "Release Manager",
             "description": "Opens the PR (or records a mock PR in replay mode).",
             "inputModes": ["application/json"], "outputModes": ["application/json"]},
            {"id": "retro-agent", "name": "Retro Agent",
             "description": "Reads the audit log and produces a graded retrospective.",
             "inputModes": ["application/json"], "outputModes": ["application/json"]},
        ],
    }


# ── Monitor API (Streamlit dashboard) ────────────────────────────────────────


@app.get("/api/personas")
def api_personas() -> list[dict]:
    agents_root = Path("agents")
    agents = []
    for d in sorted(agents_root.iterdir()):
        if not d.is_dir() or d.name.startswith("_") or d.name.startswith("."):
            continue
        files = []
        for ft in ["soul", "brain", "habits", "memory", "heartbeat"]:
            fp = d / f"{ft}.md"
            if fp.exists():
                files.append({"name": ft, "size": fp.stat().st_size})
        agents.append({"agent": d.name, "files": files})
    return agents


@app.get("/api/personas/{agent}/{file}")
def api_persona_file(agent: str, file: str) -> dict:
    fp = Path("agents") / agent / f"{file}.md"
    if not fp.exists():
        raise HTTPException(404, "file not found")
    return {"agent": agent, "file": file,
            "content": fp.read_text(encoding="utf-8"),
            "size": fp.stat().st_size}


class PersonaUpdateReq(BaseModel):
    content: str


@app.post("/api/personas/{agent}/{file}")
def api_persona_update(agent: str, file: str, req: PersonaUpdateReq) -> dict:
    fp = Path("agents") / agent / f"{file}.md"
    if not fp.exists():
        raise HTTPException(404, "file not found")
    fp.write_text(req.content, encoding="utf-8")
    return {"agent": agent, "file": file, "saved": True}


@app.get("/api/wiki/files")
def api_wiki_files() -> list[dict]:
    wiki_root = Path("wiki")
    if not wiki_root.exists():
        return []
    results = []
    for fp in sorted(wiki_root.rglob("*.md")):
        results.append({
            "path": str(fp.relative_to(wiki_root)).replace("\\", "/"),
            "size": fp.stat().st_size,
            "modified": fp.stat().st_mtime,
        })
    return results


@app.get("/api/wiki/file")
def api_wiki_file(path: str = "") -> dict:
    fp = Path("wiki") / path
    if not fp.exists():
        raise HTTPException(404, "wiki file not found")
    return {"path": path, "content": fp.read_text(encoding="utf-8"),
            "size": fp.stat().st_size}


@app.get("/api/board/status")
def api_board_status() -> dict:
    return {
        "columns": ["draft", "refinement", "ready", "in_progress", "review", "done"],
        "required_roles": ["architect", "test", "devsecops"],
        "max_files": 5, "max_loc": 400,
    }


@app.get("/api/experiments")
def api_experiments() -> list[dict]:
    results = []
    for fp in sorted(Path(".").glob("experiment_*.json"), reverse=True):
        try:
            data = json.loads(fp.read_text())
            results.append({"id": fp.stem, "config": data.get("config", {}),
                           "summary": data.get("summary", {})})
        except Exception:
            continue
    return results


@app.get("/api/experiments/{exp_id}")
def api_experiment_detail(exp_id: str) -> dict:
    fp = Path(".") / f"{exp_id}.json"
    if not fp.exists():
        raise HTTPException(404, "experiment not found")
    return json.loads(fp.read_text())


class ExperimentReq(BaseModel):
    num_sprints: int = 5
    model: str = "deepseek/deepseek-chat"
    budget: int = 300_000
    mode: str = "pull"


@app.post("/api/experiments/run")
def api_experiment_run(req: ExperimentReq) -> dict:
    import threading

    def _run():
        from orgos.agile.sprint import run_pull_sprint
        from orgos.agile.flow_metric import compute_flow_metrics
        from datetime import datetime, timezone
        import time as _t
        repo = Path(".")
        results = []
        tasks = [
            {"title": "Add docstring to takt_time", "body": "Add docstring explaining return value."},
            {"title": "Add type hints to check_ready_gate", "body": "Add type annotations."},
            {"title": "Add logging to conductor boot", "body": "Add log call."},
            {"title": "Improve scope_drift_check error", "body": "Include file counts."},
            {"title": "Add __repr__ to CompactionResult", "body": "Add __repr__ method."},
        ]
        for i in range(req.num_sprints):
            t = tasks[i % len(tasks)]
            issue = {"issue_id": str(600 + i), "title": t["title"], "body": t["body"]}
            try:
                s = run_pull_sprint(repo, issue, model=req.model, mock_pr=True,
                                    run_budget_tokens=req.budget)
                tokens = (s.spawn_result.token_usage.get("total_tokens", 0)
                          if s.spawn_result and s.spawn_result.token_usage else 0)
                flow = compute_flow_metrics(sprint_id=s.id, started_at_iso=s.started_at, n_issues=1)
                results.append({"sprint_id": s.id, "issue": t["title"],
                               "status": s.status, "tokens": tokens,
                               "flow_score": flow.flow_score})
            except Exception as e:
                results.append({"sprint_id": f"err-{i}", "status": "crashed",
                               "tokens": 0, "error": str(e)})
            _t.sleep(1)
        out = Path(f"experiment_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}.json")
        out.write_text(json.dumps({
            "config": {"num_sprints": req.num_sprints, "model": req.model,
                       "budget": req.budget, "mode": req.mode},
            "results": results,
            "summary": {
                "completed": sum(1 for r in results if r["status"] == "completed"),
                "total_tokens": sum(r["tokens"] for r in results),
            },
        }, indent=2))

    threading.Thread(target=_run, daemon=True).start()
    return {"status": "started", "num_sprints": req.num_sprints, "model": req.model}


@app.get("/api/costs")
def api_costs() -> list[dict]:
    _pm = pm if pm is not None else PMStore(PM_DB)
    rows = _pm.list_sprints(limit=50)
    out = []
    for r in rows:
        envs = json.loads(r.get("envelopes_json") or "{}")
        mode = "pull" if "architect" in envs else "legacy"
        out.append({
            "sprint_id": r["id"], "status": r["status"], "mode": mode,
            "started_at": r["started_at"], "envelope_count": len(envs),
        })
    return out


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8420)

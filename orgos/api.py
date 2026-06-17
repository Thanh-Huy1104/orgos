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
    GET  /api/proposals               — pending proposals
    POST /api/proposals/{id}/approve  — approve + apply
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
from orgos.contracts import TaskBrief

# ── Config ──────────────────────────────────────────────────────────────────

ORG_YAML = os.environ.get("ORGOS_ORG_YAML", "./examples/org.yaml")
MEMORY_DB = os.environ.get("ORGOS_MEMORY_DB", "./_orgos_memory/memory.db")
PM_DB = os.environ.get("ORGOS_PM_DB", "./_orgos_memory/pm.db")

memory: OrgMemory | None = None
pm: PMStore | None = None
org: Any = None


def load_org():
    data = yaml.safe_load(Path(ORG_YAML).read_text())
    org_data = data.get("org", {})
    org_data["departments"] = data.get("departments", [])
    org_data["handoffs"] = data.get("handoffs", [])
    return Org.model_validate(org_data) if org_data else Org(name="Default")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global memory, pm, org
    memory = OrgMemory(MEMORY_DB)
    pm = PMStore(PM_DB)
    org = load_org()
    if org:
        org.memory = memory
    yield
    if memory:
        memory.close()
    if pm:
        pm.close()


app = FastAPI(title="orgos API", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# Quant desk endpoints (Desk + Scanner dashboard pages).
from orgos.api_quant import router as quant_router  # noqa: E402

app.include_router(quant_router)


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
    path = Path(ORG_YAML)
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
    path = Path(ORG_YAML)
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text())
    return data.get("pending_credential_requests", [])


@app.get("/api/tools")
def tools():
    path = Path(ORG_YAML)
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
    path = Path("examples/policy-bank.yaml")
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
    path = Path("examples/policy-bank.yaml")
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
    path = Path("examples/policy-bank.yaml")
    if not path.exists():
        raise HTTPException(404, "Policy bank not found")
    data = yaml.safe_load(path.read_text())
    before = len(data.get("policies", []))
    data["policies"] = [p for p in data.get("policies", []) if p.get("id") != policy_id]
    if len(data["policies"]) == before:
        raise HTTPException(404, f"Policy {policy_id} not found")
    path.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False, width=120))
    return {"deleted": policy_id, "remaining": len(data["policies"])}
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
    from orgos.contracts import TaskBrief
    from orgos.spawn import spawn

    # Pick the best department and role
    goal_lower = goal.lower()
    if any(kw in goal_lower for kw in ("calendar", "schedule", "event", "appointment", "meeting", "briefing")):
        dept_name = "operations"
    elif any(kw in goal_lower for kw in ("code", "git", "test", "build", "deploy", "bug", "fix", "feature", "develop")):
        dept_name = "engineering"
    elif any(kw in goal_lower for kw in ("scan", "pair", "cointegration", "trade", "stock", "etf", "quant", "finance", "research", "search", "analyze", "report")):
        dept_name = "research"
    elif any(kw in goal_lower for kw in ("compliance", "policy", "legal", "review", "regulat")):
        dept_name = "compliance"
    elif any(kw in goal_lower for kw in ("research", "search", "find", "look up", "what is", "how to", "explain")):
        dept_name = "research"
    else:
        dept_name = "operations" if not org.find_department(dept_name) else dept_name

    dept = org.find_department(dept_name)
    if not dept:
        dept = org.departments[0]

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
    from orgos.contracts import RoleSpec, TaskBrief, PermissionTier
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
    path = Path(ORG_YAML)
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8420)

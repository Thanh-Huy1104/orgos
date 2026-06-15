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


@app.post("/api/projects")
def create_project(body: CreateProjectBody):
    """Create a new project — orchestrator decomposes goal into tasks."""
    result = spawn_project(org, body.goal, project_name=body.name, verbose=False)
    if "error" in result:
        raise HTTPException(400, result["error"])
    return {
        "project_id": result["project_id"],
        "project_name": result["project_name"],
        "tasks": len(result["tasks"]),
        "tasks_detail": result["tasks"],
    }
def dispatch_project(project_id: str):
    """Dispatch all pending tasks for a project to their departments."""
    progress = pm.get_project_progress(project_id)
    if "error" in progress:
        raise HTTPException(404, progress["error"])

    dispatched = []
    for task in progress.get("tasks", []):
        if task["status"] == "done":
            continue
        dept = org.find_department(task.get("department", "")) if org else None
        if not dept:
            dispatched.append({"task": task["title"], "status": "no_department"})
            continue
        try:
            brief = TaskBrief(objective=task["title"])
            result = run_department(org, task.get("department", ""), brief, verbose=False, record=True)
            status = result.envelope.status
            pm.update_task(task["id"], "done" if status == "completed" else "blocked", notes=result.envelope.summary[:200])
            dispatched.append({"task": task["title"], "department": task.get("department"), "status": status})
        except Exception as e:
            dispatched.append({"task": task["title"], "status": f"error: {e}"})

    pm.update_project_status(project_id, "completed" if all(d["status"] == "completed" for d in dispatched) else "active")
    return {"project_id": project_id, "dispatched": len(dispatched), "results": dispatched}


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

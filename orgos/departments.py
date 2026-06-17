"""Departments and org model — the layer above individual RoleSpecs.

A Department groups a supervisor + workers/validators/publishers +
shared MCPs/skills + SOP task templates. The Org is a collection of
departments with org-wide defaults and a notification surface.

These compile into spawn() calls — the spawn library remains the single
execution primitive.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from .contracts import PermissionTier, RoleSpec, TaskBrief
from .memory import OrgMemory, OwnerProfile


# ── SOP (Standard Operating Procedure) ────────────────────────────────────────


class SOP(BaseModel):
    """A named, reusable task template — the department's playbook."""

    name: str
    description: str = ""
    brief: TaskBrief
    cadence: str | None = None  # "daily", "weekly", "on_push", or None for on-demand


# ── Department ────────────────────────────────────────────────────────────────


class Department(BaseModel):
    """A functional department: one supervisor, N members, shared resources.

    Compiles to spawn(supervisor, brief, subordinates=members, ...).
    """

    name: str
    description: str = ""

    supervisor: RoleSpec
    members: list[RoleSpec] = Field(default_factory=list)

    shared_skills: list[str] = Field(default_factory=list)
    shared_mcps: list[Any] = Field(default_factory=list)

    sops: list[SOP] = Field(default_factory=list)

    # When True, run_department re-fetches every URL cited in the final handoff
    # and fails the run closed if any is dead/fabricated (P2 citation gate).
    # Set on departments whose output is research/claims people will rely on.
    verify_citations: bool = False

    def model_post_init(self, __context: Any) -> None:
        """Enforce invariants at construction time."""
        if self.supervisor.tier != PermissionTier.ORCHESTRATOR:
            raise ValueError(
                f"Department '{self.name}' supervisor must be tier=orchestrator, "
                f"got {self.supervisor.tier.value}"
            )
        self.supervisor.allow_delegation = True

    def _enrich_role(self, role: RoleSpec) -> RoleSpec:
        """Merge department-level resources into a member role.

        Returns a copy so the original Department spec stays pristine.
        Orchestrator-tier roles do NOT get tools (CrewAI blocks manager tools).
        """
        skills = list(role.skills)
        for s in self.shared_skills:
            if s not in skills:
                skills.append(s)

        mcps = list(role.mcp_servers)
        extra_tools = list(role.tools)

        # Orchestrators can't hold tools (CrewAI restriction) — skip tool enrichment
        if role.tier != PermissionTier.ORCHESTRATOR:
            for m in self.shared_mcps:
                if isinstance(m, dict) and m.get("type") == "gcal_tool":
                    from .gcal_tool import create_gcal_tools
                    for t in create_gcal_tools():
                        if t.name not in [getattr(et, 'name', '') for et in extra_tools]:
                            extra_tools.append(t)
                elif isinstance(m, dict) and m.get("type") == "policy_bank":
                    from .policy_bank import create_policy_bank_tool
                    t = create_policy_bank_tool()
                    if t.name not in [getattr(et, 'name', '') for et in extra_tools]:
                        extra_tools.append(t)

        for m in self.shared_mcps:
            if isinstance(m, dict) and m.get("type") in ("gcal_tool", "policy_bank"):
                continue  # handled above as native tools
            mcp_obj = _resolve_mcp(m)
            if mcp_obj is not None:
                # Deduplicate by command + args
                existing = [(getattr(em, 'command', ''), str(getattr(em, 'args', ''))) for em in mcps]
                this_key = (getattr(mcp_obj, 'command', ''), str(getattr(mcp_obj, 'args', '')))
                if this_key not in existing:
                    mcps.append(mcp_obj)

        return role.model_copy(update={"skills": skills, "mcp_servers": mcps, "tools": extra_tools})

    def all_roles(self) -> list[RoleSpec]:
        """Return supervisor + enriched members, in order."""
        return [self.supervisor] + [self._enrich_role(m) for m in self.members]

    def find_sop(self, name: str) -> SOP | None:
        for sop in self.sops:
            if sop.name == name:
                return sop
        return None


# ── Org ───────────────────────────────────────────────────────────────────────


class NotificationConfig(BaseModel):
    """Where and how the owner is notified."""

    type: str = "terminal"  # "terminal", "slack", "email", "webhook"
    webhook_url: str | None = None
    email: str | None = None


class Org(BaseModel):
    """The full company — departments + org-wide defaults.

    The single source of truth. Load from YAML for version-controlled,
    evolvable org structure.
    """

    name: str
    description: str = ""

    departments: list[Department] = Field(default_factory=list)

    owner: OwnerProfile = Field(default_factory=OwnerProfile)

    default_model: str = "gpt-4o-mini"
    default_max_budget_tokens: int | None = None
    # Ceiling on total tokens across an *entire* department run (all roles in the
    # chain combined), not per-role. The per-role cap × N roles is not a real
    # ceiling; this is. Catches a chain that bleeds tokens role-by-role.
    default_max_run_tokens: int | None = None
    default_max_iter: int = 20

    notification: NotificationConfig = Field(default_factory=NotificationConfig)

    handoffs: list[Any] = Field(default_factory=list)  # list[HandoffRule] — loaded from YAML

    # Transient — not serialized in YAML, set by the runtime.
    memory: Any = Field(default=None, exclude=True)

    def find_department(self, name: str) -> Department | None:
        for d in self.departments:
            if d.name == name:
                return d
        return None

    def all_roles(self) -> list[tuple[str, RoleSpec]]:
        """Return every role in the org, keyed by department name."""
        result: list[tuple[str, RoleSpec]] = []
        for d in self.departments:
            for r in d.all_roles():
                result.append((d.name, r))
        return result

    def use_memory(self, db_path: str | Path = "./_orgos_memory/memory.db") -> OrgMemory:
        """Attach (or return existing) memory store."""
        if self.memory is None:
            self.memory = OrgMemory(db_path)
        return self.memory


# ── MCP resolution ──────────────────────────────────────────────────────────


def _resolve_mcp(mcp_spec: Any) -> Any:
    """Resolve a symbolic MCP reference to a real MCPServerStdio object.

    Supports dict specs like ``{"type": "internet"}`` or ``{"type": "memory", "db": "..."}``.
    Returns None if the spec doesn't match a known type.
    """
    if not isinstance(mcp_spec, dict) or "type" not in mcp_spec:
        return mcp_spec  # already a real object, pass through

    mtype = mcp_spec["type"]
    if mtype == "internet":
        from .internet import create_internet_mcp
        return create_internet_mcp()
    elif mtype == "memory":
        from .memory import create_memory_mcp
        return create_memory_mcp(mcp_spec.get("db", "./_orgos_memory/memory.db"))
    elif mtype == "pm":
        from .pm import create_pm_mcp
        return create_pm_mcp(mcp_spec.get("db", "./_orgos_memory/pm.db"))
    elif mtype == "gcal":
        from .gcal import create_gcal_mcp
        return create_gcal_mcp(
            creds_path=mcp_spec.get("creds"),
            token_path=mcp_spec.get("token"),
        )

    return mcp_spec

    def use_memory(self, db_path: str | Path = "./_orgos_memory/memory.db") -> OrgMemory:
        """Attach (or return existing) memory store."""
        if self.memory is None:
            self.memory = OrgMemory(db_path)
        return self.memory


# ── Project orchestration ───────────────────────────────────────────────────


def spawn_project(
    org: Org,
    goal: str,
    *,
    project_name: str | None = None,
    approval_fn: Any | None = None,
    verbose: bool = False,
    auto_dispatch: bool = False,
) -> dict[str, Any]:
    """Decompose a goal into tasks and dispatch to departments.

    Spawns an LLM orchestrator that:
    1. Analyzes the goal
    2. Breaks it into tasks, each assigned to the best-fit department
    3. Creates a Project in the PM store
    4. Creates individual tasks linked to the project
    5. Optionally auto-dispatches each task (spawns the department)

    Returns: {"project": Project, "tasks": [...], "dispatched": [...]}
    """
    from .contracts import RoleSpec, TaskBrief, PermissionTier
    from .spawn import spawn
    from .pm import PMStore

    pm = PMStore()
    dept_names = [d.name for d in org.departments]

    # Build rich department context so the orchestrator routes accurately
    dept_context = {}
    for d in org.departments:
        supervisor = d._enrich_role(d.supervisor)
        all_tools: list[str] = []
        all_mcps: list[str] = []
        for r in d.all_roles():
            enriched = d._enrich_role(r)
            for t in enriched.tools:
                all_tools.append(getattr(t, "name", t.__class__.__name__))
            for m in enriched.mcp_servers:
                all_mcps.append(getattr(m, "command", str(type(m).__name__)))

        dept_context[d.name] = {
            "description": d.description,
            "roles": [r.name for r in d.all_roles()],
            "tools": list(set(all_tools)),
            "mcps": list(set(all_mcps)),
            "sops": [s.name for s in d.sops],
            "best_for": "",  # filled below
        }

    # Derive best_for from capabilities
    for name, ctx in dept_context.items():
        tools_str = " ".join(ctx["tools"]).lower()
        sops_str = " ".join(ctx["sops"]).lower()
        if "calendar" in tools_str or "briefing" in sops_str:
            ctx["best_for"] = "calendar management, scheduling, personal assistance"
        if "cointegration" in tools_str or "scan" in sops_str:
            ctx["best_for"] += "; data analysis, financial scanning, quantitative research"
        if "review" in sops_str or "compliance" in ctx.get("description", "").lower():
            ctx["best_for"] += "; compliance review, policy checking, legal oversight"
        ctx["best_for"] = ctx["best_for"].strip("; ")

    # Orchestrator agent: decomposes the goal
    orchestrator = RoleSpec(
        name="project-orchestrator",
        tier=PermissionTier.WORKER,
        system_prompt=(
            "You are a project manager. Given a goal, decompose it into concrete "
            "tasks and assign each to the most appropriate department.\n\n"
            "Rules:\n"
            "- 3-7 tasks per project. Be specific.\n"
            "- Each task must be assigned to an existing department.\n"
            "- Include a priority (low/medium/high/critical) per task.\n"
            "- Tasks should be ordered: dependencies first.\n"
            "- Output valid JSON only."
        ),
        model=org.default_model,
        max_iter=15,
    )

    brief = TaskBrief(
        objective=(
            f"Decompose this goal into tasks:\n\n{goal}\n\n"
            f"## Available departments (route carefully)\n"
            f"{json.dumps(dept_context, indent=2)}\n\n"
            f"Routing rules:\n"
            f"- Calendar/schedule/events → assistant (has list_calendar_events tool)\n"
            f"- Data scanning/analysis/cointegration → finance (has cointegration tool)\n"
            f"- Compliance/policy review/verification → legal (has legal-reviewer)\n"
            f"- DO NOT send data analysis to legal or calendar tasks to finance\n\n"
            f"Return a JSON array of tasks. Each task: "
            '{{"title": "...", "department": "...", "priority": "medium", "description": "..."}}'
        ),
        expected_output="JSON array of tasks with department assignments.",
        success_criteria=["Every task assigned to an existing department"],
    )

    result = spawn(orchestrator, brief, verbose=verbose)

    # Parse tasks from the orchestrator output
    tasks = []
    try:
        payload = getattr(result.envelope, "payload", "") or ""
        data = json.loads(payload) if payload else {}
        items = data if isinstance(data, list) else data.get("tasks", [])
        for item in items:
            if isinstance(item, dict) and item.get("title"):
                dept = item.get("department", dept_names[0] if dept_names else "")
                if dept not in dept_names:
                    dept = dept_names[0] if dept_names else ""
                tasks.append({
                    "title": item["title"],
                    "description": item.get("description", ""),
                    "department": dept,
                    "priority": item.get("priority", "medium"),
                })
    except (json.JSONDecodeError, TypeError, AttributeError):
        pass

    if not tasks:
        return {"error": "Orchestrator could not decompose the goal into tasks"}

    # Create project
    pname = project_name or goal[:60].strip().rstrip(".").replace(" ", "-").lower()
    project = pm.create_project(name=pname, goal=goal, owner="owner")

    # Create tasks and link to project
    task_ids = []
    for t in tasks:
        task = pm.create_task(
            title=t["title"], description=t["description"],
            department=t["department"], priority=t["priority"],
        )
        task_ids.append(task.id)

    pm.link_tasks_to_project(project.id, task_ids)

    # Auto-dispatch if requested
    dispatched = []
    if auto_dispatch:
        for t in tasks:
            dept = org.find_department(t["department"])
            if dept is None:
                continue
            try:
                tb = TaskBrief(objective=f"{t['title']}\n\n{t['description']}")
                r = run_department(org, t["department"], tb,
                                   approval_fn=approval_fn, verbose=verbose, record=True)
                dispatched.append({
                    "task": t["title"],
                    "department": t["department"],
                    "status": r.envelope.status,
                })
                # Update task status based on result
                pm.update_task(
                    [tid for tid, td in zip(task_ids, tasks) if td == t][0],
                    "done" if r.envelope.status == "completed" else "blocked",
                    notes=r.envelope.summary[:200],
                )
            except Exception as exc:
                dispatched.append({
                    "task": t["title"],
                    "department": t["department"],
                    "status": "error",
                    "error": str(exc),
                })

    pm.close()

    return {
        "project_id": project.id,
        "project_name": project.name,
        "tasks": tasks,
        "task_ids": task_ids,
        "dispatched": dispatched,
        "orchestrator_summary": result.envelope.summary[:500],
    }

    def use_memory(self, db_path: str | Path = "./_orgos_memory/memory.db") -> OrgMemory:
        """Attach (or return existing) memory store."""
        if self.memory is None:
            self.memory = OrgMemory(db_path)
        return self.memory


# ── Loading ──────────────────────────────────────────────────────────────────


def load_org(path: str | Path) -> Org:
    """Load an Org from a YAML constitution file.

    The YAML file should have top-level ``org`` and ``departments`` keys::

        org:
          name: My Org
          default_model: gpt-4o-mini
        departments:
          - name: finance
            supervisor: {name: ..., tier: orchestrator, ...}
            members: [{name: ..., tier: worker, ...}]
    """
    data = yaml.safe_load(Path(path).read_text())
    org_data = data["org"]
    org_data["departments"] = data.get("departments", [])
    org_data["handoffs"] = data.get("handoffs", [])
    org = Org.model_validate(org_data)

    # Propagate org-level defaults to roles that don't override them. Without
    # this, default_max_budget_tokens is dead config and tool-using members run
    # unbounded (a researcher web-fetch loop hit 406K tokens in testing).
    for dept in org.departments:
        for role in [dept.supervisor, *dept.members]:
            if role.max_budget_tokens is None:
                role.max_budget_tokens = org.default_max_budget_tokens
            if role.model is None:
                role.model = org.default_model

    return org


# ── Spawn helpers ─────────────────────────────────────────────────────────────


def spawn_department(
    department: Department,
    brief: TaskBrief,
    *,
    approval_fn: Any | None = None,
    verbose: bool = True,
    sequential: bool = True,
    run_budget_tokens: int | None = None,
) -> Any:
    """Compile a department into a deterministic pipeline (default) or a
    hierarchical spawn().

    Default (``sequential=True``): members run in listed order (worker →
    validator), each receiving the prior members' output via context chaining,
    then the supervisor synthesises the final handoff. Delegation is wired in
    code rather than left to the manager-LLM to *choose* — which the live runs
    showed is unreliable (the manager often narrates "I should delegate" and
    returns blocked without actually doing it).

    ``sequential=False`` falls back to the hierarchical manager-delegation path.
    """
    from .spawn import spawn, spawn_chain
    from .contracts import TaskBrief as _TaskBrief, PermissionTier as _Tier

    supervisor = department.supervisor  # orchestrator — no tool enrichment needed
    members = [department._enrich_role(m) for m in department.members]

    if not sequential or not members:
        return spawn(
            supervisor,
            brief,
            subordinates=members,
            approval_fn=approval_fn,
            verbose=verbose,
            run_budget_tokens=run_budget_tokens,
        )

    # Deterministic pipeline: each member works the brief in turn (seeing prior
    # outputs as context), then a terminal synthesis step produces the handoff.
    #
    # The synthesis role is a WORKER (not the orchestrator supervisor): in
    # sequential mode it doesn't delegate, so worker tier makes it a true
    # terminal role — which lets json_object apply on DeepSeek and yields a clean
    # HandoffEnvelope instead of free-form findings. It reuses the supervisor's
    # model but gets a synthesis prompt (the supervisor's own "delegate to X"
    # prompt is wrong for a step that has nothing to delegate to).
    synth_role = supervisor.model_copy(update={
        "tier": _Tier.WORKER,
        "allow_delegation": False,
        "tools": [],
        "mcp_servers": [],
        "system_prompt": (
            "You are a synthesis lead. Your team's findings are provided as "
            "context. Combine them into one final, accurate handoff that answers "
            "the objective. Do not redo their work; cite their findings."
        ),
    })
    synth_brief = _TaskBrief(
        objective=(
            "Synthesise the findings from your team members (provided as context) "
            "into a single definitive handoff. Use their outputs as evidence; do "
            "not redo their work.\n\nOriginal objective:\n" + brief.objective
        ),
        expected_output=brief.expected_output,
        success_criteria=brief.success_criteria or supervisor.success_criteria,
    )
    steps = [(m, brief) for m in members]
    steps.append((synth_role, synth_brief))
    return spawn_chain(
        steps,
        approval_fn=approval_fn,
        verbose=verbose,
        run_budget_tokens=run_budget_tokens,
    )


def _apply_citation_gate(result: Any, *, max_checks: int = 8) -> None:
    """Verify the URLs cited in a SpawnResult's handoff and mutate it in place.

    Appends a citation summary to the envelope notes either way. If any citation
    is definitively unreachable (dead/fabricated URL), downgrades the handoff to
    needs_revision and clears success_criteria_met — the fail-closed gate.
    """
    from .citations import verify_text

    env = result.envelope
    text = (env.summary or "") + "\n" + (env.payload or "")
    report = verify_text(text, max_checks=max_checks)
    if not report.checks:
        return  # nothing cited — nothing to gate

    env.notes = (env.notes or "") + f" [citations: {report.summary()}]"
    if not report.passed:
        env.status = "needs_revision"
        env.success_criteria_met = False
        env.notes += " [gate: dead/fabricated citation — see report]"


def run_department(
    org: Org,
    department_name: str,
    brief: TaskBrief,
    *,
    approval_fn: Any | None = None,
    verbose: bool = True,
    record: bool = True,
    sequential: bool = True,
    run_budget_tokens: int | None = None,
    verify_citations: bool | None = None,
):
    """Run a department with memory recording and context injection.

    1. Finds the department in the org.
    2. Injects memory context (recent runs, owner prefs, token spend) into the brief.
    3. Spawns the department.
    4. Records the run in OrgMemory.

    Returns the SpawnResult.
    """
    department = org.find_department(department_name)
    if department is None:
        raise ValueError(
            f"Department '{department_name}' not found in org '{org.name}'. "
            f"Available: {[d.name for d in org.departments]}"
        )

    memory = org.use_memory()

    # Determine artifact type BEFORE context injection modifies the brief
    artifact_type = department_name
    for s in (department.sops if hasattr(department, 'sops') else []):
        if s.brief.objective == brief.objective:
            artifact_type = s.name
            break

    # Inject memory context into the brief
    ctx = memory.context_for(
        department=department_name,
        role=department.supervisor.name,
        owner=org.owner,
    )
    if ctx:
        brief = brief.model_copy(
            update={"objective": f"{brief.objective}\n\n---\n{ctx}"}
        )

    # Fall back to the org-wide run ceiling when the caller doesn't override it.
    if run_budget_tokens is None:
        run_budget_tokens = org.default_max_run_tokens

    result = spawn_department(
        department,
        brief,
        approval_fn=approval_fn,
        verbose=verbose,
        sequential=sequential,
        run_budget_tokens=run_budget_tokens,
    )

    # ── Citation gate (P2) ────────────────────────────────────────────────
    # Re-fetch every URL the handoff cites and fail closed on a dead/fabricated
    # one. Code-enforced ground truth — not the validator LLM's self-report.
    do_verify = department.verify_citations if verify_citations is None else verify_citations
    if do_verify and result.envelope.status == "completed":
        _apply_citation_gate(result)

    # ── Observability (P3) ────────────────────────────────────────────────
    # Per-run metrics + MAST failure-mode tag. Runs after the citation gate so
    # a gate-induced downgrade is reflected in the classification.
    from .observability import compute_metrics, record_metrics

    metrics = compute_metrics(
        result.run_id, result.envelope, result.token_usage,
        department=department_name,
    )
    if metrics.failure_mode is not None:
        result.envelope.notes = (
            (result.envelope.notes or "")
            + f" [failure_mode: {metrics.failure_mode.code} {metrics.failure_mode.label}]"
        )
    record_metrics(metrics)

    if record:
        memory.record_run(
            department=department_name,
            role=department.supervisor.name,
            envelope=result.envelope,
            brief=brief,
            token_usage=result.token_usage,
            org=org.name,
            run_id=result.run_id,
        )

    # ── Cross-department handoffs ─────────────────────────────────────
    if org.handoffs:
        from .handoff import HandoffBus

        bus = HandoffBus(org)
        for h in org.handoffs:
            if isinstance(h, dict):
                from .handoff import HandoffRule
                bus.add_rule(HandoffRule.model_validate(h))
            else:
                bus.add_rule(h)

        # Publish this run as an artifact
        bus.publish(
            department_name, artifact_type,
            result.envelope, result.run_id, result.token_usage,
        )

        # Check and execute triggers
        triggered = bus.check_triggers(
            from_department=department_name,
            artifact_type=artifact_type,
        )
        for t in triggered:
            from .scheduler import notify_owner
            notify_owner(
                org, "handoff_triggered",
                f"{department_name} → {t['rule'].to_department} "
                f"({t['rule'].artifact_type})",
            )
            try:
                bus.execute_trigger(t["rule"], approval_fn=approval_fn, verbose=verbose)
            except Exception as exc:
                notify_owner(
                    org, "handoff_failed",
                    f"{department_name} → {t['rule'].to_department}: {exc}",
                    level="warning",
                )

    return result

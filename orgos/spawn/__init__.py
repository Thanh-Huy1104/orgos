"""orgos.spawn — the spawn engine.

A self-contained library for compiling agent specs into running CrewAI crews
under enforced permission tiers, token/loop/tool budgets, approval gates, and a
tool-level audit trail. It has no import edge into orgos's concrete tools,
subagents, or domain code — those depend on it, not the other way around.

Public surface:

  Specs & contracts
    RoleSpec, TaskBrief, HandoffEnvelope, PermissionTier, TierPolicy,
    TIER_POLICY, budget_llm, and the CATEGORY_* tool-category constants.

  Engine entry points
    spawn(role, brief, ...)         — one agent (or orchestrator + subordinates)
    spawn_chain([(role, brief), ...]) — a sequential, context-chained pipeline
    SpawnResult                      — the validated result (envelope + trail id)

  Tool framework
    GatedToolBase, ApprovalFn        — base class for approval-gated tools

  Observability & safety
    make_audit_callback, make_task_callback, make_budget_callback, cli_approval
    trace_tool, read_trail           — the research-trail capture/read pair
    RunBudget, BudgetExceeded, LoopDetected, ToolBudgetExceeded
"""

from .contracts import (
    CATEGORY_COMPUTE,
    CATEGORY_ORCHESTRATE,
    CATEGORY_PUBLISH,
    CATEGORY_READ,
    CATEGORY_SANDBOX,
    TIER_POLICY,
    HandoffEnvelope,
    PermissionTier,
    RoleSpec,
    TaskBrief,
    TierPolicy,
    budget_llm,
)
from .toolbase import ApprovalFn, GatedToolBase
from .audit import (
    BudgetExceeded,
    LoopDetected,
    RunBudget,
    ToolBudgetExceeded,
    cli_approval,
    make_audit_callback,
    make_budget_callback,
    make_task_callback,
    read_trail,
    recent_trails,
    trace_tool,
)
from .engine import SpawnResult, spawn, spawn_chain
from .rubric import (
    GRADERS,
    GradeResult,
    Rubric,
    chain_until,
    grade,
    register_grader,
    spawn_until,
)

__all__ = [
    # contracts
    "RoleSpec",
    "TaskBrief",
    "HandoffEnvelope",
    "PermissionTier",
    "TierPolicy",
    "TIER_POLICY",
    "budget_llm",
    "CATEGORY_READ",
    "CATEGORY_SANDBOX",
    "CATEGORY_COMPUTE",
    "CATEGORY_PUBLISH",
    "CATEGORY_ORCHESTRATE",
    # tool framework
    "GatedToolBase",
    "ApprovalFn",
    # engine
    "spawn",
    "spawn_chain",
    "SpawnResult",
    # rubric loop
    "Rubric",
    "GradeResult",
    "grade",
    "spawn_until",
    "chain_until",
    "register_grader",
    "GRADERS",
    # observability & safety
    "make_audit_callback",
    "make_task_callback",
    "make_budget_callback",
    "cli_approval",
    "trace_tool",
    "read_trail",
    "recent_trails",
    "RunBudget",
    "BudgetExceeded",
    "LoopDetected",
    "ToolBudgetExceeded",
]

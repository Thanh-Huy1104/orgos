"""orgos.spawn.governance — the spawn engine.

A self-contained library for running agent specs under enforced permission
tiers, token/loop/tool budgets, approval gates, and a tool-level audit trail.
It has no import edge into any consumer's concrete tools, subagents, or
domain code — those depend on it, not the other way around.

The core (contracts, audit, persona loading) depends on pydantic only and
always imports. The CrewAI execution layer (``spawn``, ``spawn_chain``,
``GatedToolBase``, rubric grading) needs the ``crewai`` extra and
is loaded lazily — accessing those names without crewai installed raises an
ImportError that says exactly that.

Public surface:

  Specs & contracts (core — always available)
    RoleSpec, TaskBrief, HandoffEnvelope, PermissionTier, TierPolicy,
    TIER_POLICY, budget_llm, and the CATEGORY_* tool-category constants.

  Observability & safety (core — always available)
    make_audit_callback, make_task_callback, make_budget_callback, cli_approval
    trace_tool, read_trail, recent_trails — the research-trail capture/read pair
    RunBudget, BudgetExceeded, LoopDetected, ToolBudgetExceeded

  Engine entry points (require crewai)
    spawn(role, brief, ...)          — one agent (or orchestrator + subordinates)
    spawn_chain([(role, brief), ...]) — a sequential, context-chained pipeline
    SpawnResult                       — the validated result (envelope + trail id)

  Tool framework (requires crewai)
    GatedToolBase, ApprovalFn         — base class for approval-gated tools
"""

from __future__ import annotations

from typing import Any

from .audit import (
    BudgetExceeded,
    DelegationDepthExceeded,
    LoopDetected,
    RunBudget,
    ToolBudgetExceeded,
    append_record,
    cli_approval,
    make_audit_callback,
    make_budget_callback,
    make_task_callback,
    read_trail,
    recent_trails,
    trace_tool,
    verify_trail,
)
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
from .persona_loader import load_agent
from .persona_schema import PersonaValidationError
from .result import SpawnResult, TierViolation, ToolConfigurationError
from .runner import ToolDef, arun_governed, run_governed
from .tiers import filter_tools_for_tier, requires_approval

# Names that live in crewai-dependent modules, resolved lazily so that
# `import orgos.spawn.governance` works without the crewai extra installed.
_LAZY_EXPORTS: dict[str, str] = {
    "spawn": ".engine",
    "spawn_chain": ".engine",
    "GatedToolBase": ".toolbase",
    "ApprovalFn": ".toolbase",
    "GRADERS": ".rubric",
    "GradeResult": ".rubric",
    "Rubric": ".rubric",
}


def __getattr__(name: str) -> Any:
    modpath = _LAZY_EXPORTS.get(name)
    if modpath is None:
        raise AttributeError(
            f"module 'orgos.spawn.governance' has no attribute {name!r}"
        )
    import importlib  # noqa: PLC0415

    try:
        mod = importlib.import_module(modpath, __name__)
    except ImportError as e:
        raise ImportError(
            f"orgos.spawn.governance.{name} requires the CrewAI execution layer: "
            "pip install 'crewai'"
        ) from e
    return getattr(mod, name)


__all__ = [
    # core
    "BudgetExceeded",
    "DelegationDepthExceeded",
    "LoopDetected",
    "RunBudget",
    "ToolBudgetExceeded",
    "cli_approval",
    "make_audit_callback",
    "make_budget_callback",
    "make_task_callback",
    "read_trail",
    "recent_trails",
    "trace_tool",
    "append_record",
    "verify_trail",
    "CATEGORY_COMPUTE",
    "CATEGORY_ORCHESTRATE",
    "CATEGORY_PUBLISH",
    "CATEGORY_READ",
    "CATEGORY_SANDBOX",
    "TIER_POLICY",
    "HandoffEnvelope",
    "PermissionTier",
    "RoleSpec",
    "TaskBrief",
    "TierPolicy",
    "budget_llm",
    "load_agent",
    "PersonaValidationError",
    "SpawnResult",
    "TierViolation",
    "ToolConfigurationError",
    "ToolDef",
    "run_governed",
    "arun_governed",
    "filter_tools_for_tier",
    "requires_approval",
    # lazy (require crewai)
    *_LAZY_EXPORTS,
]

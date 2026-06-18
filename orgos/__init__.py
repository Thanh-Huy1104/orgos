"""orgos — a company of agents on CrewAI."""

from .spawn import (
    TIER_POLICY,
    BudgetExceeded,
    HandoffEnvelope,
    PermissionTier,
    RoleSpec,
    SpawnResult,
    TaskBrief,
    TierPolicy,
    budget_llm,
    cli_approval,
    make_audit_callback,
    make_budget_callback,
    read_trail,
    spawn,
    spawn_chain,
    trace_tool,
)
from .departments import (
    Department,
    NotificationConfig,
    Org,
    SOP,
    load_org,
    run_department,
    spawn_department,
    spawn_project,
)
from .evolve import OrgAnalyzer, Proposal, ProposalType, apply_proposal, review_proposals
from .handoff import HandoffBus, HandoffRule
from .mcps.gcal import create_gcal_mcp
from .mcps.internet import create_internet_mcp
from .legal import (
    DEFAULT_POLICY,
    LegalPolicy,
    LegalPolicyRule,
    legal_review,
    legal_review_with_agent,
)
from .memory import (
    OrgMemory,
    OwnerProfile,
    create_memory_mcp,
)
from .pm import PMStore, create_pm_mcp
from .scheduler import Scheduler, notify_owner

__all__ = [
    "RoleSpec",
    "TaskBrief",
    "HandoffEnvelope",
    "PermissionTier",
    "TierPolicy",
    "TIER_POLICY",
    "budget_llm",
    "spawn",
    "spawn_chain",
    "SpawnResult",
    "BudgetExceeded",
    "make_audit_callback",
    "make_budget_callback",
    "cli_approval",
    "Department",
    "Org",
    "SOP",
    "NotificationConfig",
    "OrgMemory",
    "OwnerProfile",
    "Scheduler",
    "notify_owner",
    "LegalPolicy",
    "LegalPolicyRule",
    "DEFAULT_POLICY",
    "legal_review",
    "legal_review_with_agent",
    "create_memory_mcp",
    "PMStore",
    "create_pm_mcp",
    "create_internet_mcp",
    "create_gcal_mcp",
    "HandoffBus",
    "HandoffRule",
    "OrgAnalyzer",
    "Proposal",
    "ProposalType",
    "review_proposals",
    "apply_proposal",
    "load_org",
    "run_department",
    "spawn_department",
    "spawn_project",
]

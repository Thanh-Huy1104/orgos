"""Pre-built subagent role specs."""

from .engineering_team import (
    engineer_role,
    product_manager_role,
    qa_validator_role,
    release_manager_role,
    retro_agent_role,
    sprint_lead_role,
)

from .scrum_team import (
    architect_role,
    devsecops_role,
    po_role,
    scrum_master_role,
    test_role,
)

__all__ = [
    "sprint_lead_role",
    "product_manager_role",
    "engineer_role",
    "qa_validator_role",
    "release_manager_role",
    "retro_agent_role",
    "po_role",
    "scrum_master_role",
    "architect_role",
    "test_role",
    "devsecops_role",
]

"""Pre-built subagent role specs."""

from .engineering_team import (
    engineer_role,
    product_manager_role,
    qa_validator_role,
    release_manager_role,
    retro_agent_role,
    sprint_lead_role,
)

__all__ = [
    "sprint_lead_role",
    "product_manager_role",
    "engineer_role",
    "qa_validator_role",
    "release_manager_role",
    "retro_agent_role",
]

"""Pre-built subagent role factories for the Scrum team.

Only the five personas the dispatcher uses are exported. Legacy
engineering_team role factories are gone.
"""

from .scrum_team import (
    architect_role,
    devsecops_role,
    po_role,
    scrum_master_role,
    test_role,
)

# Legacy names used only by orgos/agile/sprint.py's older paths. sprint.py is
# kept because dispatcher imports helpers from it; these aliases exist so its
# imports don't blow up. None of them are executed by the CLI paths.
release_manager_role = scrum_master_role
engineer_role = architect_role
product_manager_role = po_role
qa_validator_role = test_role
sprint_lead_role = scrum_master_role
retro_agent_role = scrum_master_role

__all__ = [
    "architect_role",
    "devsecops_role",
    "po_role",
    "scrum_master_role",
    "test_role",
    "release_manager_role",
    "engineer_role",
    "product_manager_role",
    "qa_validator_role",
    "sprint_lead_role",
    "retro_agent_role",
]

from orgos.spawn import PermissionTier
from orgos.subagents.engineering_team import (
    sprint_lead_role, product_manager_role, engineer_role,
    qa_validator_role, release_manager_role, retro_agent_role,
)


def test_sprint_lead_is_orchestrator():
    r = sprint_lead_role()
    assert r.tier == PermissionTier.ORCHESTRATOR
    assert r.allow_delegation is True


def test_pm_is_worker_with_short_brief_floor():
    r = product_manager_role()
    assert r.tier == PermissionTier.WORKER
    assert "Product Manager" in r.system_prompt or "PM" in r.system_prompt


def test_engineer_is_worker_and_accepts_extra_tools():
    from orgos.tools.bash import BashTool
    r = engineer_role(extra_tools=[BashTool()])
    assert r.tier == PermissionTier.WORKER
    assert any(getattr(t, "name", "").lower() == "bash" for t in r.tools)


def test_qa_is_validator_readonly():
    r = qa_validator_role()
    assert r.tier == PermissionTier.VALIDATOR


def test_release_manager_is_publisher():
    r = release_manager_role()
    assert r.tier == PermissionTier.PUBLISHER


def test_retro_agent_is_validator():
    r = retro_agent_role()
    assert r.tier == PermissionTier.VALIDATOR


def test_all_roles_have_success_criteria():
    for factory in (sprint_lead_role, product_manager_role, engineer_role,
                    qa_validator_role, release_manager_role, retro_agent_role):
        r = factory()
        assert r.success_criteria, f"{r.name} has no success_criteria"

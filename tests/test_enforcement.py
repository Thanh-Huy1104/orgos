"""Enforcement test suite — asserts the safety invariants directly.

These tests verify that orgos's permission model is enforced in code, not
in prompts. Run with:

    PYTHONPATH=/home/th python tests/test_enforcement.py

Each test targets a specific invariant from the DESIGN.md security model.
They do NOT require an LLM key — they test the policy engine, not the agent.
"""

import copy
import sys
from typing import Any
from unittest.mock import patch

import pytest

from crewai.tools import BaseTool, tool
from pydantic import BaseModel, Field

from orgos import (
    HandoffEnvelope,
    PermissionTier,
    RoleSpec,
    TaskBrief,
)
from orgos.contracts import CATEGORY_PUBLISH, CATEGORY_READ, CATEGORY_SANDBOX
from orgos.tools import BashTool, GatedToolBase
from orgos.spawn import (
    _TierViolation,
    _build_task,
    _UNSET,
    _enforce_tier,
    _make_logged_agent,
    _read_envelope,
    _wire_gates,
)


# ── Tool fixtures ────────────────────────────────────────────────────────────

class _EmptyArgs(BaseModel):
    """Schema for tools with no arguments."""
    pass


class _DummyReadTool(GatedToolBase):
    name: str = "ReadFile"
    description: str = "Read a file."
    args_schema: type[BaseModel] = _EmptyArgs
    tool_category: str = CATEGORY_READ

    def _run(self, **kwargs: Any) -> str:
        return "data"


class _DummySandboxTool(GatedToolBase):
    name: str = "RunScript"
    description: str = "Run a script."
    args_schema: type[BaseModel] = _EmptyArgs
    tool_category: str = CATEGORY_SANDBOX

    def _run(self, **kwargs: Any) -> str:
        return "ok"


class _DummyPublishTool(GatedToolBase):
    name: str = "DeployToProd"
    description: str = "Deploy to production."
    args_schema: type[BaseModel] = _EmptyArgs
    tool_category: str = CATEGORY_PUBLISH

    def _run(self, **kwargs: Any) -> str:
        return "deployed"


class _UncategorizedTool(BaseTool):
    """A tool with no tool_category at all — default is empty string."""
    name: str = "MysteryTool"
    description: str = "Does something."
    args_schema: type[BaseModel] = _EmptyArgs

    def _run(self, **kwargs: Any) -> str:
        return "???"


class _PlainToolNoGate(BaseTool):
    """A vanilla BaseTool (not GatedToolBase) with a publish category."""
    name: str = "PlainPublisher"
    description: str = "Publishes without gate."
    args_schema: type[BaseModel] = _EmptyArgs
    tool_category: str = CATEGORY_PUBLISH

    def _run(self, **kwargs: Any) -> str:
        return "published"


@tool("PlainReadTool")
def _plain_read_tool(query: str) -> str:
    """Reads data. tool_category is not set (plain @tool)."""
    return f"result for {query}"


# ── Helper ───────────────────────────────────────────────────────────────────

def _make_role(name: str, tier: PermissionTier, tools: list[Any]) -> RoleSpec:
    return RoleSpec(
        name=name, description=f"{name} role",
        tier=tier, system_prompt="You are a test agent.",
        tools=tools, model="gpt-4o-mini",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Tier enforcement invariants
# ═══════════════════════════════════════════════════════════════════════════════

class TestTierEnforcement:
    """_enforce_tier must reject tools the tier disallows."""

    def test_validator_rejects_sandbox_category(self):
        role = _make_role("v", PermissionTier.VALIDATOR, [_DummySandboxTool()])
        with pytest.raises(_TierViolation, match="category"):
            _enforce_tier(role)

    def test_validator_accepts_read_category(self):
        role = _make_role("v", PermissionTier.VALIDATOR, [_DummyReadTool()])
        tools = _enforce_tier(role)
        assert len(tools) == 1

    def test_validator_rejects_uncategorized_tool(self):
        role = _make_role("v", PermissionTier.VALIDATOR, [_UncategorizedTool()])
        with pytest.raises(_TierViolation, match="category"):
            _enforce_tier(role)

    def test_orchestrator_rejects_all_tools(self):
        role = _make_role("o", PermissionTier.ORCHESTRATOR, [_DummyReadTool()])
        with pytest.raises(_TierViolation, match="category"):
            _enforce_tier(role)

    def test_worker_accepts_any_category(self):
        role = _make_role("w", PermissionTier.WORKER, [
            _DummySandboxTool(), _DummyReadTool(), _UncategorizedTool(),
        ])
        tools = _enforce_tier(role)
        assert len(tools) == 3

    def test_non_publisher_rejects_publish_category(self):
        role = _make_role("w", PermissionTier.WORKER, [_DummyPublishTool()])
        with pytest.raises(_TierViolation, match="publish"):
            _enforce_tier(role)

    def test_publisher_accepts_publish_category(self):
        role = _make_role("pub", PermissionTier.PUBLISHER, [_DummyPublishTool()])
        tools = _enforce_tier(role)
        assert len(tools) == 1

    def test_gateability_check_rejects_plain_tool_on_publisher(self):
        """Publisher requires_approval=["*"] — every tool must be gateable."""
        role = _make_role("pub", PermissionTier.PUBLISHER, [_PlainToolNoGate()])
        with pytest.raises(_TierViolation, match="GatedToolBase"):
            _enforce_tier(role)

    def test_gateability_check_rejects_plain_tool_on_publish_category(self):
        """Even on worker, a publish-category tool must be gateable."""
        role = _make_role("w", PermissionTier.WORKER, [_PlainToolNoGate()])
        # publish-category on non-publisher is caught by check #4 first,
        # but if it were a publisher, check #5 would catch it.
        # On worker it's denied by check #4.
        with pytest.raises(_TierViolation):
            _enforce_tier(role)


class TestGateWiring:
    """_wire_gates must fail closed."""

    def test_refuses_to_wire_without_approval_fn(self):
        role = _make_role("pub", PermissionTier.PUBLISHER, [_DummyPublishTool()])
        tools = _enforce_tier(role)
        with pytest.raises(_TierViolation, match="no approval_fn"):
            _wire_gates(tools, role, None)

    def test_wires_gate_with_approval_fn(self):
        role = _make_role("pub", PermissionTier.PUBLISHER, [_DummyPublishTool()])
        tools = _enforce_tier(role)
        wired = _wire_gates(tools, role, lambda r, t, i: True)
        assert wired[0]._gate_required is True
        assert wired[0].approval_fn is not None

    def test_gated_tool_denies_when_required_but_no_fn(self):
        tool = _DummyPublishTool()
        tool._gate_required = True  # simulate wire
        assert tool._check_gate({}) is False  # fail-closed

    def test_gated_tool_allows_when_fn_returns_true(self):
        tool = _DummyPublishTool()
        tool._gate_required = True
        tool.approval_fn = lambda r, t, i: True
        assert tool._check_gate({}) is True

    def test_worker_tools_not_gated(self):
        """Worker has requires_approval=[] — no gating."""
        role = _make_role("w", PermissionTier.WORKER, [_DummySandboxTool()])
        tools = _enforce_tier(role)
        wired = _wire_gates(tools, role, lambda r, t, i: False)
        assert wired[0]._gate_required is False


class TestToolIsolation:
    """Shared tool instances must not cross-mutate."""

    def test_copy_isolation(self):
        shared = _DummySandboxTool()
        roles = [
            _make_role(f"r{i}", PermissionTier.WORKER, [shared])
            for i in range(2)
        ]
        agents = [
            _make_logged_agent(r, f"run-{i}", lambda r, t, i: True)
            for i, r in enumerate(roles)
        ]
        # Each agent should have its own tool instance
        ids = [id(a.tools[0]) for a in agents]
        assert len(set(ids)) == 2, f"Expected 2 distinct instances, got {ids}"

    def test_original_role_tools_not_mutated(self):
        """The RoleSpec's own tool list should not be modified by spawn."""
        tool = _DummySandboxTool()
        role = _make_role("w", PermissionTier.WORKER, [tool])
        orig_agent_role = tool._agent_role
        _make_logged_agent(role, "run-1", lambda r, t, i: True)
        # Original tool instance should be untouched
        assert tool._agent_role == orig_agent_role


class TestBuildTaskSentinel:
    """_build_task sentinel must distinguish None from default."""

    def test_unset_defaults_to_handoff_envelope(self):
        role = _make_role("w", PermissionTier.WORKER, [])
        agent = role.to_agent()
        task = _build_task(role, TaskBrief(objective="t"), agent)
        assert task.output_pydantic is HandoffEnvelope

    def test_none_disables_schema(self):
        role = _make_role("w", PermissionTier.WORKER, [])
        agent = role.to_agent()
        task = _build_task(role, TaskBrief(objective="t"), agent,
                          output_pydantic=None)
        assert task.output_pydantic is None


class TestEnvelopeValidation:
    """_read_envelope must fail closed."""

    def test_empty_output_is_failed(self):
        env = _read_envelope("", "test")
        assert env.status == "failed"

    def test_non_json_output_is_needs_revision(self):
        env = _read_envelope("just some text, no json", "test")
        assert env.status == "needs_revision"

    def test_valid_pydantic_passes(self):
        env = HandoffEnvelope(
            role="test", status="completed", summary="ok",
            success_criteria_met=True,
        )
        result = _read_envelope("", "test", env)
        assert result.status == "completed"

    def test_completed_without_criteria_demoted(self):
        env = HandoffEnvelope(
            role="test", status="completed", summary="ok",
            success_criteria_met=False,
        )
        result = _read_envelope("", "test", env)
        assert result.status == "needs_revision"


class TestVerboseOverride:
    """to_agent must allow verbose override via **overrides."""

    def test_verbose_defaults_true(self):
        role = _make_role("w", PermissionTier.WORKER, [])
        agent = role.to_agent()
        assert agent.verbose is True

    def test_verbose_can_be_set_false(self):
        role = _make_role("w", PermissionTier.WORKER, [])
        agent = role.to_agent(verbose=False)
        assert agent.verbose is False

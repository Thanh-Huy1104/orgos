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
    _kickoff_with_fallback,
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

    def test_orchestrator_allows_read_and_orchestrate(self):
        """Orchestrator can use read and orchestrate category tools."""
        role = _make_role("o", PermissionTier.ORCHESTRATOR, [_DummyReadTool()])
        tools = _enforce_tier(role)
        assert len(tools) == 1

    def test_orchestrator_rejects_sandbox_tools(self):
        """Orchestrator rejects non-read, non-orchestrate tools."""
        role = _make_role("o", PermissionTier.ORCHESTRATOR, [_DummySandboxTool()])
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


class TestStructuredOutputFallback:
    """Providers that reject json_schema (e.g. DeepSeek) must not pay a wasted
    structured-output probe when structured_output is False."""

    @staticmethod
    def _make_build(calls: list):
        class FakeCrew:
            def __init__(self, structured):
                self.structured = structured

            def kickoff(self):
                calls.append(self.structured)
                if self.structured:
                    raise RuntimeError("This response_format type is unavailable now")
                return "ok"

        return lambda structured: FakeCrew(structured)

    def test_probe_false_single_pass(self):
        calls: list = []
        out = _kickoff_with_fallback(self._make_build(calls), probe_structured=False)
        assert calls == [False]   # no wasted structured attempt
        assert out == "ok"

    def test_probe_true_falls_back(self):
        calls: list = []
        out = _kickoff_with_fallback(self._make_build(calls), probe_structured=True)
        assert calls == [True, False]   # probe, then fallback
        assert out == "ok"

    def test_role_default_governs(self):
        role = _make_role("ds", PermissionTier.WORKER, [])
        role.structured_output = False
        assert role.structured_output is False

    def test_json_object_mode_set_when_unstructured(self):
        role = _make_role("ds", PermissionTier.WORKER, [])
        role.model = "deepseek/deepseek-chat"
        role.structured_output = False
        llm = role._build_llm()
        assert llm.response_format == {"type": "json_object"}

    def test_no_json_object_mode_when_structured(self):
        role = _make_role("oa", PermissionTier.WORKER, [])
        role.model = "gpt-4o-mini"
        role.structured_output = True
        llm = role._build_llm()
        assert getattr(llm, "response_format", None) is None

    def test_no_json_object_on_tool_using_deepseek_role(self):
        # json_object would suppress native tool calls — must NOT be set when
        # a DeepSeek role has tools, even though it can't use json_schema.
        role = _make_role("ds", PermissionTier.WORKER, [BashTool()])
        role.model = "deepseek/deepseek-v4-pro"
        llm = role._build_llm()
        assert getattr(llm, "response_format", None) is None

    def test_no_json_object_on_mcp_role(self):
        # MCP servers are tools too — a role with MCPs must not get json_object,
        # or its tool calls break and "json"-less ReAct calls 400.
        role = _make_role("ds", PermissionTier.WORKER, [])
        role.model = "deepseek/deepseek-v4-pro"
        role.mcp_servers = [{"type": "internet"}]
        llm = role._build_llm()
        assert getattr(llm, "response_format", None) is None

    def test_no_json_object_on_orchestrator_or_delegator(self):
        for setup in ("orchestrator", "delegation"):
            role = _make_role("ds", PermissionTier.WORKER, [])
            role.model = "deepseek/deepseek-v4-pro"
            if setup == "orchestrator":
                role.tier = PermissionTier.ORCHESTRATOR
            else:
                role.allow_delegation = True
            llm = role._build_llm()
            assert getattr(llm, "response_format", None) is None, setup

    def test_deepseek_provider_skips_json_schema_probe(self):
        # Even with structured_output left True (default), a DeepSeek model must
        # resolve effective_structured() to False so spawn skips the probe.
        role = _make_role("ds", PermissionTier.WORKER, [])
        role.model = "deepseek/deepseek-v4-pro"
        assert role.structured_output is True
        assert role.effective_structured() is False

    def test_openai_provider_keeps_json_schema(self):
        role = _make_role("oa", PermissionTier.WORKER, [])
        role.model = "gpt-4o-mini"
        assert role.effective_structured() is True


class TestJsonExtraction:
    """_read_envelope must recover a JSON handoff wrapped in prose/markdown."""

    def _env(self, status="completed"):
        return (
            '{"role": "w", "status": "%s", "summary": "ok", '
            '"success_criteria_met": true}' % status
        )

    def test_plain_json(self):
        env = _read_envelope(self._env(), "w")
        assert env.status == "completed"

    def test_fenced_json_block(self):
        raw = f"Here is my handoff:\n```json\n{self._env()}\n```\nDone."
        env = _read_envelope(raw, "w")
        assert env.status == "completed"

    def test_json_embedded_in_prose(self):
        raw = f"Sure! {self._env()} hope that helps"
        env = _read_envelope(raw, "w")
        assert env.status == "completed"

    def test_pure_markdown_no_json_is_needs_revision(self):
        raw = "## Handoff\n- role: w\n- status: completed"
        env = _read_envelope(raw, "w")
        assert env.status == "needs_revision"

    def test_brace_in_string_not_miscounted(self):
        raw = '{"role": "w", "status": "blocked", "summary": "has } brace"}'
        env = _read_envelope(f"noise {raw} noise", "w")
        assert env.status == "blocked"


class TestRunBudget:
    """The chain-level run budget aborts on the aggregate across roles, catching
    a chain that bleeds tokens role-by-role under each per-role cap."""

    def test_aggregate_aborts_even_when_no_single_role_exceeds(self):
        from orgos.audit import RunBudget, BudgetExceeded

        rb = RunBudget(cap=100)
        rb.add(60, "roleA")  # under cap on its own
        with pytest.raises(BudgetExceeded):
            rb.add(60, "roleB")  # 120 > 100 aggregate
        assert rb.used == 120

    def test_under_cap_does_not_abort(self):
        from orgos.audit import RunBudget

        rb = RunBudget(cap=1000)
        rb.add(300, "a")
        rb.add(400, "b")
        assert rb.used == 700

    def test_negative_delta_clamped(self):
        from orgos.audit import RunBudget

        rb = RunBudget(cap=1000)
        rb.add(-50, "a")  # never decrements
        assert rb.used == 0


class TestLoopDetection:
    """The audit step_callback aborts when the same (tool, input) action repeats
    past max_repeats — the failure the token budget can't catch (cheap loops)."""

    @staticmethod
    def _step(tool, tool_input):
        from types import SimpleNamespace

        return SimpleNamespace(tool=tool, tool_input=tool_input, thought="")

    def test_repeated_action_raises_loop_detected(self):
        from orgos.audit import make_audit_callback, LoopDetected

        cb = make_audit_callback("looper", "test-loop", max_repeats=3)
        step = self._step("web_fetch", "http://x")
        with pytest.raises(LoopDetected):
            for _ in range(10):
                cb(step)

    def test_distinct_actions_do_not_trip(self):
        from orgos.audit import make_audit_callback

        cb = make_audit_callback("worker", "test-distinct", max_repeats=3)
        for i in range(10):
            cb(self._step("web_fetch", f"http://x/{i}"))  # all distinct → no raise

    def test_under_threshold_ok(self):
        from orgos.audit import make_audit_callback

        cb = make_audit_callback("worker", "test-under", max_repeats=4)
        step = self._step("web_search", "same query")
        for _ in range(4):  # exactly max_repeats, not over
            cb(step)

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
from orgos.spawn.governance.contracts import CATEGORY_PUBLISH, CATEGORY_READ, CATEGORY_SANDBOX
from orgos.tools import BashTool
from orgos.spawn.governance.toolbase import GatedToolBase
from orgos.spawn.governance.engine import (
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
        from orgos.spawn.governance.audit import RunBudget, BudgetExceeded

        rb = RunBudget(cap=100)
        rb.add(60, "roleA")  # under cap on its own
        with pytest.raises(BudgetExceeded):
            rb.add(60, "roleB")  # 120 > 100 aggregate
        assert rb.used == 120

    def test_under_cap_does_not_abort(self):
        from orgos.spawn.governance.audit import RunBudget

        rb = RunBudget(cap=1000)
        rb.add(300, "a")
        rb.add(400, "b")
        assert rb.used == 700

    def test_negative_delta_clamped(self):
        from orgos.spawn.governance.audit import RunBudget

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
        from orgos.spawn.governance.audit import make_audit_callback, LoopDetected

        cb = make_audit_callback("looper", "test-loop", max_repeats=3)
        step = self._step("web_fetch", "http://x")
        with pytest.raises(LoopDetected):
            for _ in range(10):
                cb(step)

    def test_distinct_actions_do_not_trip(self):
        from orgos.spawn.governance.audit import make_audit_callback

        cb = make_audit_callback("worker", "test-distinct", max_repeats=3)
        for i in range(10):
            cb(self._step("web_fetch", f"http://x/{i}"))  # all distinct → no raise

    def test_under_threshold_ok(self):
        from orgos.spawn.governance.audit import make_audit_callback

        cb = make_audit_callback("worker", "test-under", max_repeats=4)
        step = self._step("web_search", "same query")
        for _ in range(4):  # exactly max_repeats, not over
            cb(step)


class TestToolCallBudget:
    """A brief's tool_call_budget caps total tool calls, even varied ones —
    the cure for unbounded fan-out (distinct from the loop guard)."""

    @staticmethod
    def _step(tool, tool_input):
        from types import SimpleNamespace

        return SimpleNamespace(tool=tool, tool_input=tool_input, thought="")

    def test_varied_calls_aborts_past_budget(self):
        from orgos.spawn.governance.audit import make_audit_callback, ToolBudgetExceeded

        cb = make_audit_callback("fanout", "test-toolbudget", max_actions=5)
        with pytest.raises(ToolBudgetExceeded):
            for i in range(20):  # all distinct URLs → loop guard never fires
                cb(self._step("web_fetch", f"http://x/{i}"))

    def test_within_budget_ok(self):
        from orgos.spawn.governance.audit import make_audit_callback

        cb = make_audit_callback("worker", "test-toolbudget-ok", max_actions=5)
        for i in range(5):  # exactly the budget, not over
            cb(self._step("web_fetch", f"http://x/{i}"))

    def test_no_budget_means_unbounded(self):
        from orgos.spawn.governance.audit import make_audit_callback

        cb = make_audit_callback("worker", "test-nobudget", max_actions=None)
        for i in range(50):
            cb(self._step("web_fetch", f"http://x/{i}"))  # no cap → no raise


class TestBriefRendering:
    """source_guidance and tool_call_budget must surface in the task prompt."""

    def test_source_guidance_in_description(self):
        from orgos import TaskBrief

        brief = TaskBrief(objective="find X", source_guidance="prefer arxiv and HF")
        desc = brief.render_description()
        assert "prefer arxiv and HF" in desc

    def test_tool_call_budget_in_description(self):
        from orgos import TaskBrief

        brief = TaskBrief(objective="find X", tool_call_budget=6)
        desc = brief.render_description()
        assert "at most 6 tool calls" in desc

    def test_absent_fields_not_rendered(self):
        from orgos import TaskBrief

        desc = TaskBrief(objective="find X").render_description()
        assert "Where to look" not in desc
        assert "Tool-call budget" not in desc


class TestCitationVerification:
    """Deterministic citation grading: reachability is the hard gate, term
    overlap a soft signal, transient errors never downgrade."""

    @staticmethod
    def _fetcher(mapping):
        # mapping: url -> (status_code, body) or an Exception to raise
        def fetch(url, timeout):
            v = mapping[url]
            if isinstance(v, Exception):
                raise v
            return v
        return fetch

    def test_extract_urls_dedup_and_trailing_punct(self):
        pytest.importorskip("orgos.citations", reason="feature removed from orgos; dormant test predates the orgos.spawn migration")
        from orgos.citations import extract_urls

        text = "see https://a.com/x. and https://a.com/x again, plus https://b.org/y)."
        assert extract_urls(text) == ["https://a.com/x", "https://b.org/y"]

    def test_404_is_unreachable(self):
        pytest.importorskip("orgos.citations", reason="feature removed from orgos; dormant test predates the orgos.spawn migration")
        from orgos.citations import verify_citation

        c = verify_citation("https://x.com/dead", "claim",
                            fetcher=self._fetcher({"https://x.com/dead": (404, "")}))
        assert c.status == "unreachable"

    def test_200_with_terms_is_supported(self):
        pytest.importorskip("orgos.citations", reason="feature removed from orgos; dormant test predates the orgos.spawn migration")
        from orgos.citations import verify_citation

        body = "Llama 3.1 8B is a small open model with strong reasoning."
        c = verify_citation("https://hf.co/llama", "Llama 3.1 8B strong reasoning model",
                            fetcher=self._fetcher({"https://hf.co/llama": (200, body)}))
        assert c.status == "supported"

    def test_200_without_terms_is_weak(self):
        pytest.importorskip("orgos.citations", reason="feature removed from orgos; dormant test predates the orgos.spawn migration")
        from orgos.citations import verify_citation

        c = verify_citation("https://hf.co/x", "quantum chromodynamics lattice gauge",
                            fetcher=self._fetcher({"https://hf.co/x": (200, "cooking recipes")}))
        assert c.status == "weak"

    def test_timeout_is_uncertain_not_fail(self):
        pytest.importorskip("orgos.citations", reason="feature removed from orgos; dormant test predates the orgos.spawn migration")
        from orgos.citations import verify_citation

        c = verify_citation("https://slow.com", "claim",
                            fetcher=self._fetcher({"https://slow.com": TimeoutError("slow")}))
        assert c.status == "uncertain"

    def test_5xx_is_uncertain(self):
        pytest.importorskip("orgos.citations", reason="feature removed from orgos; dormant test predates the orgos.spawn migration")
        from orgos.citations import verify_citation

        c = verify_citation("https://x.com", "claim",
                            fetcher=self._fetcher({"https://x.com": (503, "")}))
        assert c.status == "uncertain"

    def test_report_fails_only_on_unreachable(self):
        pytest.importorskip("orgos.citations", reason="feature removed from orgos; dormant test predates the orgos.spawn migration")
        from orgos.citations import verify_text

        text = "good https://ok.com/a\nbad https://ok.com/dead\nweak https://ok.com/w"
        fetch = self._fetcher({
            "https://ok.com/a": (200, "a a a"),
            "https://ok.com/dead": (404, ""),
            "https://ok.com/w": (200, "unrelated"),
        })
        rep = verify_text(text, fetcher=fetch)
        assert rep.passed is False  # one unreachable

    def test_report_passes_when_no_unreachable(self):
        pytest.importorskip("orgos.citations", reason="feature removed from orgos; dormant test predates the orgos.spawn migration")
        from orgos.citations import verify_text

        text = "good https://ok.com/a and weak https://ok.com/w"
        fetch = self._fetcher({
            "https://ok.com/a": (200, "a"),
            "https://ok.com/w": (200, "x"),
        })
        assert verify_text(text, fetcher=fetch).passed is True


class TestCitationGate:
    """_apply_citation_gate downgrades a completed handoff with a dead URL."""

    def test_dead_url_downgrades_to_needs_revision(self, monkeypatch):
        from types import SimpleNamespace
        from orgos import HandoffEnvelope
        pytest.importorskip("orgos.departments", reason="feature removed from orgos; dormant test predates the orgos.spawn migration")
        from orgos import departments, citations

        monkeypatch.setattr(citations, "_http_fetch",
                            lambda url, timeout: (404, ""))
        env = HandoffEnvelope(role="r", status="completed",
                              summary="Finding. Source: https://fake.example/dead",
                              success_criteria_met=True)
        result = SimpleNamespace(envelope=env)
        departments._apply_citation_gate(result)
        assert env.status == "needs_revision"
        assert env.success_criteria_met is False
        assert "citation" in (env.notes or "").lower()

    def test_live_url_keeps_completed(self, monkeypatch):
        from types import SimpleNamespace
        from orgos import HandoffEnvelope
        pytest.importorskip("orgos.departments", reason="feature removed from orgos; dormant test predates the orgos.spawn migration")
        from orgos import departments, citations

        monkeypatch.setattr(citations, "_http_fetch",
                            lambda url, timeout: (200, "real content here"))
        env = HandoffEnvelope(role="r", status="completed",
                              summary="Finding. Source: https://real.example/ok",
                              success_criteria_met=True)
        result = SimpleNamespace(envelope=env)
        departments._apply_citation_gate(result)
        assert env.status == "completed"
        assert env.success_criteria_met is True


class TestSearchBackends:
    """Pluggable search: parsers map provider JSON to a common shape, and the
    dispatcher tries keyed providers first, falling through on error/empty."""

    class _FakeAsyncClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    def test_parse_tavily(self):
        pytest.importorskip("orgos.mcps.internet_mcp", reason="feature removed from orgos; dormant test predates the orgos.spawn migration")
        from orgos.mcps import internet_mcp

        data = {"results": [{"title": "T", "url": "https://t", "content": "body"}]}
        out = internet_mcp._parse_tavily(data)
        assert out == [{"title": "T", "url": "https://t", "snippet": "body"}]

    def test_parse_brave(self):
        pytest.importorskip("orgos.mcps.internet_mcp", reason="feature removed from orgos; dormant test predates the orgos.spawn migration")
        from orgos.mcps import internet_mcp

        data = {"web": {"results": [{"title": "B", "url": "https://b", "description": "d"}]}}
        assert internet_mcp._parse_brave(data)[0]["url"] == "https://b"

    def test_parse_serper(self):
        pytest.importorskip("orgos.mcps.internet_mcp", reason="feature removed from orgos; dormant test predates the orgos.spawn migration")
        from orgos.mcps import internet_mcp

        data = {"organic": [{"title": "S", "link": "https://s", "snippet": "snip"}]}
        out = internet_mcp._parse_serper(data)
        assert out[0]["url"] == "https://s" and out[0]["snippet"] == "snip"

    def test_keyed_provider_wins(self, monkeypatch):
        import asyncio
        pytest.importorskip("orgos.mcps.internet_mcp", reason="feature removed from orgos; dormant test predates the orgos.spawn migration")
        from orgos.mcps import internet_mcp

        async def fake(client, q, limit, key):
            return [{"title": "T", "url": "u", "snippet": "s"}]

        monkeypatch.setattr(internet_mcp, "_PROVIDERS", [("tavily", "TAVILY_API_KEY", fake)])
        monkeypatch.setenv("TAVILY_API_KEY", "x")
        monkeypatch.setattr(internet_mcp.httpx, "AsyncClient", self._FakeAsyncClient)
        backend, results, _ = asyncio.run(internet_mcp._run_search("q", 5))
        assert backend == "tavily" and len(results) == 1

    def test_no_key_skips_to_ddg(self, monkeypatch):
        import asyncio
        pytest.importorskip("orgos.mcps.internet_mcp", reason="feature removed from orgos; dormant test predates the orgos.spawn migration")
        from orgos.mcps import internet_mcp

        async def boom(client, q, limit, key):
            raise AssertionError("must not call a keyless provider")

        monkeypatch.setattr(internet_mcp, "_PROVIDERS", [("tavily", "TAVILY_API_KEY", boom)])
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        monkeypatch.setattr(internet_mcp.httpx, "AsyncClient", self._FakeAsyncClient)
        monkeypatch.setattr(internet_mcp, "_ddg", lambda q, l: [{"title": "d", "url": "u", "snippet": "s"}])
        backend, results, _ = asyncio.run(internet_mcp._run_search("q", 5))
        assert backend == "duckduckgo"

    def test_empty_provider_falls_through(self, monkeypatch):
        import asyncio
        pytest.importorskip("orgos.mcps.internet_mcp", reason="feature removed from orgos; dormant test predates the orgos.spawn migration")
        from orgos.mcps import internet_mcp

        async def empty(client, q, limit, key):
            return []

        monkeypatch.setattr(internet_mcp, "_PROVIDERS", [("tavily", "TAVILY_API_KEY", empty)])
        monkeypatch.setenv("TAVILY_API_KEY", "x")
        monkeypatch.setattr(internet_mcp.httpx, "AsyncClient", self._FakeAsyncClient)
        monkeypatch.setattr(internet_mcp, "_ddg", lambda q, l: [{"title": "d", "url": "u", "snippet": "s"}])
        backend, results, errors = asyncio.run(internet_mcp._run_search("q", 5))
        assert backend == "duckduckgo"
        assert any("empty" in e for e in errors)

    def test_all_fail_returns_none(self, monkeypatch):
        import asyncio
        pytest.importorskip("orgos.mcps.internet_mcp", reason="feature removed from orgos; dormant test predates the orgos.spawn migration")
        from orgos.mcps import internet_mcp

        async def err(client, q, limit, key):
            raise ValueError("rate limited")

        monkeypatch.setattr(internet_mcp, "_PROVIDERS", [("tavily", "TAVILY_API_KEY", err)])
        monkeypatch.setenv("TAVILY_API_KEY", "x")
        monkeypatch.setattr(internet_mcp.httpx, "AsyncClient", self._FakeAsyncClient)
        monkeypatch.setattr(internet_mcp, "_ddg", lambda q, l: [])
        backend, results, errors = asyncio.run(internet_mcp._run_search("q", 5))
        assert backend == "none" and results == []
        assert any("ValueError" in e for e in errors)


class TestFailureClassification:
    """MAST failure-mode tagging keys off the controls' diagnostic strings."""

    @staticmethod
    def _env(status, summary="", notes=None):
        from orgos import HandoffEnvelope

        return HandoffEnvelope(role="r", status=status, summary=summary, notes=notes)

    def test_completed_is_not_a_failure(self):
        pytest.importorskip("orgos.observability", reason="feature removed from orgos; dormant test predates the orgos.spawn migration")
        from orgos.observability import classify_failure

        assert classify_failure(self._env("completed", "all good")) is None

    def test_loop_is_step_repetition(self):
        pytest.importorskip("orgos.observability", reason="feature removed from orgos; dormant test predates the orgos.spawn migration")
        from orgos.observability import classify_failure

        fm = classify_failure(self._env("failed", "Loop detected: role 'r' issued..."))
        assert fm.code == "FM-1.3" and fm.label == "step_repetition"

    def test_run_budget_is_unaware_of_termination(self):
        pytest.importorskip("orgos.observability", reason="feature removed from orgos; dormant test predates the orgos.spawn migration")
        from orgos.observability import classify_failure

        fm = classify_failure(self._env("failed", "Run budget exceeded: 260000 tokens"))
        assert fm.code == "FM-1.5"

    def test_tool_budget_is_unaware_of_termination(self):
        pytest.importorskip("orgos.observability", reason="feature removed from orgos; dormant test predates the orgos.spawn migration")
        from orgos.observability import classify_failure

        fm = classify_failure(self._env("failed", "Tool-call budget exceeded: 9 calls"))
        assert fm.code == "FM-1.5"

    def test_citation_gate_is_incorrect_verification(self):
        pytest.importorskip("orgos.observability", reason="feature removed from orgos; dormant test predates the orgos.spawn migration")
        from orgos.observability import classify_failure

        fm = classify_failure(self._env("needs_revision", "x", notes="[gate: dead/fabricated citation — see report]"))
        assert fm.code == "FM-3.3"

    def test_criteria_unmet_is_premature_termination(self):
        pytest.importorskip("orgos.observability", reason="feature removed from orgos; dormant test predates the orgos.spawn migration")
        from orgos.observability import classify_failure

        fm = classify_failure(self._env("needs_revision", "x", notes="[gate: success_criteria_met was False]"))
        assert fm.code == "FM-3.1"

    def test_malformed_handoff_is_disobey_spec(self):
        pytest.importorskip("orgos.observability", reason="feature removed from orgos; dormant test predates the orgos.spawn migration")
        from orgos.observability import classify_failure

        fm = classify_failure(self._env("needs_revision", "output was not valid JSON: ##hi"))
        assert fm.code == "FM-1.1"

    def test_kickoff_error_is_execution_error(self):
        pytest.importorskip("orgos.observability", reason="feature removed from orgos; dormant test predates the orgos.spawn migration")
        from orgos.observability import classify_failure

        fm = classify_failure(self._env("failed", "kickoff failed: ConnectionError"))
        assert fm.code == "EXEC"

    def test_unmatched_failure_is_unknown(self):
        pytest.importorskip("orgos.observability", reason="feature removed from orgos; dormant test predates the orgos.spawn migration")
        from orgos.observability import classify_failure

        fm = classify_failure(self._env("blocked", "waiting on something opaque"))
        assert fm.code == "UNKNOWN"


class TestMetrics:
    """Per-run metrics from the audit log, and aggregation over many runs."""

    def test_compute_counts_tool_calls(self, tmp_path):
        import json
        from orgos import HandoffEnvelope
        pytest.importorskip("orgos.observability", reason="feature removed from orgos; dormant test predates the orgos.spawn migration")
        from orgos.observability import compute_metrics

        log = tmp_path / "chain-abc.jsonl"
        log.write_text("\n".join(json.dumps(r) for r in [
            {"type": "action", "tool": "web_search"},
            {"type": "action", "tool": "web_fetch"},
            {"type": "finish", "output": "done"},
        ]) + "\n")
        env = HandoffEnvelope(role="r", status="completed", summary="ok",
                              success_criteria_met=True)
        m = compute_metrics("chain-abc", env, {"total_tokens": 1234},
                            department="research", audit_dir=tmp_path)
        assert m.tool_calls == 2 and m.steps == 3
        assert m.total_tokens == 1234 and m.failure_mode is None

    def test_summarize_aggregates(self, tmp_path):
        from orgos import HandoffEnvelope
        pytest.importorskip("orgos.observability", reason="feature removed from orgos; dormant test predates the orgos.spawn migration")
        from orgos.observability import compute_metrics, record_metrics, summarize_metrics

        path = tmp_path / "metrics.jsonl"
        ok = HandoffEnvelope(role="r", status="completed", summary="ok",
                             success_criteria_met=True)
        bad = HandoffEnvelope(role="r", status="failed",
                              summary="Loop detected: ...")
        record_metrics(compute_metrics("c1", ok, {"total_tokens": 100}, audit_dir=tmp_path), path=path)
        record_metrics(compute_metrics("c2", bad, {"total_tokens": 300}, audit_dir=tmp_path), path=path)
        s = summarize_metrics(path=path)
        assert s["runs"] == 2
        assert s["completion_rate"] == 0.5
        assert s["avg_total_tokens"] == 200
        assert any("FM-1.3" in k for k in s["failure_modes"])

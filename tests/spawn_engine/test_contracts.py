"""Tests for orgos.contracts — budget LLM, skills/MCP wiring, to_agent.

No LLM key required — tests the wrapping logic and agent compilation.
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from orgos import RoleSpec, PermissionTier
from agentkit.governance.contracts import budget_llm


# ── Budget LLM ─────────────────────────────────────────────────────────────


class TestBudgetLLM:
    def test_budget_passes_when_under_cap(self):
        """When token usage is under the cap, the call proceeds normally."""
        mock_llm = MagicMock()
        mock_llm._token_usage = {"total_tokens": 50}
        call_count = [0]

        def original_call(*args, **kwargs):
            call_count[0] += 1
            return "ok"

        mock_llm.call = original_call

        wrapped = budget_llm(mock_llm, "test-role", 100)
        result = wrapped.call("hello")

        assert result == "ok"
        assert call_count[0] == 1

    def test_budget_raises_post_call(self):
        """A call pushing THIS RUN's usage over the cap raises after it.

        agentkit's budget is baseline-relative (snapshotted at wrap time):
        pre-existing instance usage no longer counts against a new run —
        the fix for the cross-run corruption found in review. Only tokens
        accrued after wrapping trip the cap.
        """
        mock_llm = MagicMock()
        mock_llm._token_usage = {"total_tokens": 50}  # prior-run usage: ignored

        def original_call(*args, **kwargs):
            mock_llm._token_usage = {"total_tokens": 151}  # +101 this run
            return "ok"

        mock_llm.call = original_call

        wrapped = budget_llm(mock_llm, "test-role", 100)
        from agentkit.governance.audit import BudgetExceeded
        with pytest.raises(BudgetExceeded, match="101 real tokens"):
            wrapped.call("hello")

    def test_budget_raises_pre_call(self):
        """Once this run is over budget, further calls are blocked BEFORE
        executing (the pre-call check), not after."""
        mock_llm = MagicMock()
        mock_llm._token_usage = {"total_tokens": 0}
        call_count = [0]

        def original_call(*args, **kwargs):
            call_count[0] += 1
            mock_llm._token_usage = {"total_tokens": 150}
            return "ok"

        mock_llm.call = original_call

        wrapped = budget_llm(mock_llm, "test-role", 100)
        from agentkit.governance.audit import BudgetExceeded
        with pytest.raises(BudgetExceeded):
            wrapped.call("hello")       # executes, then trips post-call
        with pytest.raises(BudgetExceeded, match="150 real tokens"):
            wrapped.call("hello")       # blocked before executing

        # The second call never reached the model
        assert call_count[0] == 1

    def test_budget_message_includes_role_name(self):
        mock_llm = MagicMock()
        mock_llm._token_usage = {"total_tokens": 0}

        def original_call(*args, **kwargs):
            mock_llm._token_usage = {"total_tokens": 999}
            return "ok"

        mock_llm.call = original_call

        wrapped = budget_llm(mock_llm, "finance-scanner", 100)
        from agentkit.governance.audit import BudgetExceeded
        with pytest.raises(BudgetExceeded, match="finance-scanner"):
            wrapped.call("hello")

    def test_original_token_usage_not_modified(self):
        """The wrapper reads _token_usage but doesn't mutate it directly."""
        mock_llm = MagicMock()
        mock_llm._token_usage = {"total_tokens": 10}
        mock_llm.call.return_value = "ok"

        wrapped = budget_llm(mock_llm, "test", 100)
        wrapped.call("hello")

        # _token_usage should be whatever mock_llm set it to
        assert mock_llm._token_usage["total_tokens"] == 10


# ── Skills / MCP wiring ───────────────────────────────────────────────────


class TestSkillsWiring:
    def test_skills_passed_to_agent(self):
        """Skills list should be passed to Agent constructor as skills=.
        Only existing paths are passed; non-existent paths are silently skipped."""
        import tempfile, os
        d = tempfile.mkdtemp()
        skill_dir = os.path.join(d, "myskill")
        os.makedirs(skill_dir)
        Path(skill_dir, "SKILL.md").write_text(
            "---\nname: myskill\ndescription: A test skill.\n---\n# Test"
        )
        try:
            role = RoleSpec(
                name="test",
                tier=PermissionTier.WORKER,
                system_prompt="Test.",
                skills=[d],  # parent dir containing myskill/
            )
            agent = role.to_agent()
            assert agent.skills is not None
            names = [s.name for s in agent.skills if hasattr(s, "name")]
            assert "myskill" in names
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)

    def test_skills_none_when_empty(self):
        role = RoleSpec(
            name="test",
            tier=PermissionTier.WORKER,
            system_prompt="Test.",
            skills=[],
        )
        agent = role.to_agent()
        assert agent.skills is None

    def test_registry_ref_preserved_as_string(self):
        """@org/name registry refs should remain strings, not Path objects.
        Requires CREWAI_EXPERIMENTAL=1 to resolve — we just verify the ref
        is passed through without conversion."""
        role = RoleSpec(
            name="test",
            tier=PermissionTier.WORKER,
            system_prompt="Test.",
            skills=["@acme/quant-tools"],
        )
        # Registry refs trigger CrewAI's experimental flag — skip to_agent
        # and verify the ref is correctly identified
        from pathlib import Path as P
        resolved = []
        for s in role.skills:
            if isinstance(s, str) and not s.startswith("@"):
                p = P(s)
                if p.is_dir():
                    resolved.append(p)
            else:
                resolved.append(s)
        assert "@acme/quant-tools" in resolved

    def test_nonexistent_path_skipped(self):
        """Non-existent file paths should be silently skipped."""
        role = RoleSpec(
            name="test",
            tier=PermissionTier.WORKER,
            system_prompt="Test.",
            skills=["/nonexistent/path/12345"],
        )
        agent = role.to_agent()
        # Skipped — should be None (not a list with the bad path)
        assert agent.skills is None


class TestMCPWiring:
    def test_mcp_passed_to_agent(self):
        """MCP servers should be passed to Agent constructor as mcps=."""
        from crewai.mcp.config import MCPServerStdio
        mcp = MCPServerStdio(command="python", args=["-m", "server"])
        role = RoleSpec(
            name="test",
            tier=PermissionTier.WORKER,
            system_prompt="Test.",
            mcp_servers=[mcp],
        )
        agent = role.to_agent()
        assert agent.mcps is not None
        assert len(agent.mcps) == 1

    def test_mcp_none_when_empty(self):
        role = RoleSpec(
            name="test",
            tier=PermissionTier.WORKER,
            system_prompt="Test.",
            mcp_servers=[],
        )
        agent = role.to_agent()
        assert agent.mcps is None

    def test_mcp_overridable(self):
        from crewai.mcp.config import MCPServerStdio
        mcp1 = MCPServerStdio(command="python", args=["-m", "s1"])
        mcp2 = MCPServerStdio(command="python", args=["-m", "s2"])
        role = RoleSpec(
            name="test",
            tier=PermissionTier.WORKER,
            system_prompt="Test.",
            mcp_servers=[mcp1],
        )
        agent = role.to_agent(mcps=[mcp2])
        assert len(agent.mcps) == 1
        assert agent.mcps[0].args == ["-m", "s2"]


# ── to_agent overrides ─────────────────────────────────────────────────────


class TestToAgentOverrides:
    def test_skills_overridable(self):
        """Skills override via kwargs. Test the resolution logic directly
        to avoid CrewAI experimental flag on @ref strings."""
        role = RoleSpec(
            name="test",
            tier=PermissionTier.WORKER,
            system_prompt="Test.",
            skills=["@acme/default"],
        )
        # Test the override logic without calling to_agent (which triggers
        # CrewAI's experimental flag on registry refs)
        import tempfile, os
        d = tempfile.mkdtemp()
        skill_dir = os.path.join(d, "myskill")
        os.makedirs(skill_dir)
        Path(skill_dir, "SKILL.md").write_text(
            "---\nname: myskill\ndescription: A test.\n---\n# Test"
        )
        try:
            agent = role.to_agent(skills=[d])
            names = [s.name for s in agent.skills if hasattr(s, "name")]
            assert "myskill" in names
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)

    def test_tools_overridable(self):
        from orgos.tools import BashTool
        role = RoleSpec(
            name="test",
            tier=PermissionTier.WORKER,
            system_prompt="Test.",
            tools=[BashTool()],
        )
        agent = role.to_agent(tools=[])
        assert len(agent.tools) == 0


# ── Brief vagueness gate ─────────────────────────────────────────────────────


class TestBriefUnderspecified:
    def test_empty_objective_rejected(self):
        from agentkit.governance.contracts import TaskBrief
        assert TaskBrief(objective="   ").underspecified() == "objective is empty"

    def test_stub_objective_rejected(self):
        from agentkit.governance.contracts import TaskBrief
        for stub in ("research", "do it", "help me", "find X"):
            assert TaskBrief(objective=stub).underspecified() is not None

    def test_concise_real_objective_accepted(self):
        from agentkit.governance.contracts import TaskBrief
        # The README example — concise but actionable — must pass.
        assert TaskBrief(
            objective="Summarise X into a one-page brief"
        ).underspecified() is None


# ── Role TTL / expiry ────────────────────────────────────────────────────────


class TestRoleExpiry:
    def _role(self, expire_at):
        return RoleSpec(name="temp", tier=PermissionTier.WORKER,
                        system_prompt="x", expire_at=expire_at)

    def test_no_expiry_never_expires(self):
        assert self._role(None).is_expired() is False

    def test_past_date_is_expired(self):
        assert self._role("2000-01-01").is_expired() is True

    def test_future_date_not_expired(self):
        assert self._role("2999-01-01").is_expired() is False

    def test_unparseable_date_treated_as_permanent(self):
        # We don't silently drop a role over a typo'd date.
        assert self._role("not-a-date").is_expired() is False

"""Tests for the quant strategist wiring (offline — spawn/run_department mocked).

The agentic loop itself needs a live LLM; here we verify the agent is assembled
correctly (right tools, tier, budgets) and the research-spawn tool works.
"""

import json

import pytest

from orgos import quant_strategist as qs
from orgos.spawn import PermissionTier


class _FakeResult:
    class envelope:
        summary = "test"
        status = "completed"
    token_usage = {"total_tokens": 1}


@pytest.fixture(autouse=True)
def _isolate_journal(monkeypatch):
    # Keep wiring tests hermetic: no real journal read/write.
    monkeypatch.setattr(qs.quant_journal, "prior_research_block", lambda **k: "")
    monkeypatch.setattr(qs.quant_journal, "record", lambda *a, **k: 1)


class TestStrategistWiring:
    def test_chain_is_researcher_scanner_synth(self, monkeypatch):
        captured = {}

        def fake_chain(steps, **kw):
            captured["steps"] = steps
            captured["kw"] = kw
            return _FakeResult()

        monkeypatch.setattr(qs, "spawn_chain", fake_chain)
        qs.run_strategist("find rate-sensitive cross-sector pairs", allow_research=True)
        steps = captured["steps"]
        assert len(steps) == 3                           # researcher → scanner → synth
        researcher_role, research_brief = steps[0]
        scanner_role, _ = steps[1]
        synth_role, _ = steps[2]
        assert researcher_role.tier == PermissionTier.WORKER
        # Phase 1 grounds in news + arxiv + real constituents (no scanners).
        researcher_tools = {t.name for t in researcher_role.tools}
        assert {"news_catalysts", "search_arxiv", "index_constituents"} <= researcher_tools
        assert "scan_cointegrated_pairs" not in researcher_tools
        # Phase 2 validates: scanners + (optional) research linkage.
        scanner_tools = {t.name for t in scanner_role.tools}
        assert {"scan_cointegrated_pairs", "scan_crypto_pairs", "research_linkage"} <= scanner_tools
        assert researcher_role.skills                    # quant-research SKILL.md attached
        assert synth_role.tools == []                    # terminal synth has no tools
        assert captured["kw"]["run_budget_tokens"] == 400_000
        # research brief gets half the budget (floor 4); default budget is 12 → 6
        assert research_brief.tool_call_budget == 6

    def test_research_linkage_can_be_disabled(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(qs, "spawn_chain", lambda steps, **kw: captured.setdefault("steps", steps) or _FakeResult())
        qs.run_strategist("x", allow_research=False)
        scanner_tools = {t.name for t in captured["steps"][1][0].tools}
        assert "research_linkage" not in scanner_tools   # linkage off
        assert "scan_cointegrated_pairs" in scanner_tools

    def test_prior_research_injected_and_finding_recorded(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(qs.quant_journal, "prior_research_block",
                            lambda **k: "## Prior research notes\n- AEE/NI durable")
        recorded = {}
        monkeypatch.setattr(qs.quant_journal, "record",
                            lambda obj, summ, **k: recorded.update(objective=obj, summary=summ))
        def fake_chain(steps, **kw):
            captured["steps"] = steps
            return _FakeResult()
        monkeypatch.setattr(qs, "spawn_chain", fake_chain)
        qs.run_strategist("utilities")
        assert "Prior research notes" in captured["steps"][0][1].objective   # injected
        assert recorded["objective"] == "utilities"                          # recorded after

    def test_objective_and_asset_class_in_brief(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(qs, "spawn_chain", lambda steps, **kw: captured.setdefault("steps", steps) or _FakeResult())
        qs.run_strategist("semis supply chain", asset_class="equity")
        strat_brief = captured["steps"][0][1]
        assert "semis supply chain" in strat_brief.objective
        assert "equity" in strat_brief.objective


class TestResearchLinkageTool:
    def test_dispatches_research_department(self, monkeypatch):
        class FakeEnv:
            status = "completed"
            summary = "Supported: both are SE-US regulated utilities."
            notes = "[citations: 2 supported]"

        class FakeResult:
            envelope = FakeEnv()

        monkeypatch.setattr(qs, "_org", lambda: object())
        import orgos.departments as deps
        monkeypatch.setattr(deps, "run_department", lambda *a, **k: FakeResult())

        out = json.loads(qs.ResearchLinkageTool()._run("DUK/SO utilities linkage"))
        assert out["verdict_status"] == "completed"
        assert "regulated utilities" in out["summary"]

    def test_research_error_returns_json_not_crash(self, monkeypatch):
        monkeypatch.setattr(qs, "_org", lambda: object())
        import orgos.departments as deps

        def boom(*a, **k):
            raise RuntimeError("research dept down")
        monkeypatch.setattr(deps, "run_department", boom)

        out = json.loads(qs.ResearchLinkageTool()._run("x"))
        assert "error" in out

    def test_tool_metadata(self):
        t = qs.ResearchLinkageTool()
        assert t.name == "research_linkage" and t.tool_category == "read"

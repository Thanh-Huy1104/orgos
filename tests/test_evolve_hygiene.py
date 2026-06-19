"""Evolve hygiene: actionable cadence apply, content dedup, and volume gating."""

import tempfile
from pathlib import Path

from orgos.evolve import Proposal, ProposalStore, ProposalType, apply_proposal

_ORG_YAML = """\
org:
  name: TestOrg
  default_model: gpt-4o-mini
departments:
  - name: research
    supervisor:
      name: lead
      tier: orchestrator
      system_prompt: Lead.
    sops:
      - name: daily_briefing
        cadence: daily
        brief:
          objective: Daily research briefing for the desk.
"""


# ── Fix A: MODIFY_CADENCE actually changes a SOP cadence ──────────────────────


class TestCadenceApply:
    def test_cadence_change_lands(self, tmp_path):
        path = tmp_path / "org.yaml"
        path.write_text(_ORG_YAML)
        prop = Proposal.make(
            ProposalType.MODIFY_CADENCE, "research", "slow it", "too expensive",
            changes={"sop_name": "daily_briefing", "cadence": "weekly"},
        )
        res = apply_proposal(prop, path)
        assert res["applied"] is True
        assert "cadence: weekly" in path.read_text()

    def test_no_actionable_change_fails_honestly(self, tmp_path):
        path = tmp_path / "org.yaml"
        path.write_text(_ORG_YAML)
        # the old free-text 'recommendation' shape — nothing the apply path honours
        prop = Proposal.make(
            ProposalType.MODIFY_CADENCE, "research", "vague", "x",
            changes={"recommendation": "reduce frequency"},
        )
        res = apply_proposal(prop, path)
        assert res["applied"] is False
        assert "No actionable change" in res["message"]


# ── Fix B: content dedup ──────────────────────────────────────────────────────


class TestDedup:
    def _store(self):
        d = tempfile.mkdtemp()
        return ProposalStore(db_path=str(Path(d) / "p.db"))

    def test_identical_proposal_not_restacked(self):
        store = self._store()
        p1 = Proposal.make(ProposalType.ADD_ROLE, "research", "Add reviewer", "because")
        p2 = Proposal.make(ProposalType.ADD_ROLE, "research", "Add reviewer", "because")  # new id
        assert store.add(p1) is True
        assert store.add(p2) is False              # deduped on content
        assert len(store.list_pending()) == 1

    def test_denied_proposal_can_recur(self):
        store = self._store()
        p1 = Proposal.make(ProposalType.ADD_ROLE, "research", "Add reviewer", "because")
        store.add(p1)
        store.deny(p1.id)
        p2 = Proposal.make(ProposalType.ADD_ROLE, "research", "Add reviewer", "because")
        assert store.add(p2) is True               # denied one doesn't block a re-propose

    def test_add_all_counts_only_new(self):
        store = self._store()
        a = Proposal.make(ProposalType.ADD_ROLE, "research", "Add reviewer", "x")
        b = Proposal.make(ProposalType.ADD_ROLE, "research", "Add reviewer", "x")
        assert store.add_all([a, b]) == 1


# ── Fix C: volume gate ────────────────────────────────────────────────────────


class TestVolumeGate:
    def test_low_volume_department_proposes_nothing(self):
        from orgos.evolve import OrgAnalyzer, _MIN_RUNS_FOR_PROPOSAL

        class _Run:
            status = "failed"
            summary = "missing api key unauthorized"

        class _Mem:
            def recent_runs(self, department, limit=20):
                return [_Run()] * (_MIN_RUNS_FOR_PROPOSAL - 1)  # below the gate
            def department_spend(self, name, days):
                return {"total_tokens": 0}

        class _Dept:
            name = "research"
            sops = []
            def all_roles(self):
                return []

        class _Org:
            departments = [_Dept()]
            default_max_budget_tokens = 100000
            default_model = "gpt-4o-mini"
            def use_memory(self):
                return _Mem()
            def find_department(self, n):
                return object()  # legal exists → no legal-gap proposal either

        props = OrgAnalyzer(_Org()).basic_proposals()
        assert props == []  # gated: too few runs to judge

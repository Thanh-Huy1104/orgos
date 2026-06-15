"""Tests for orgos.departments — Department, Org, SOP, YAML loading.

No LLM key required — tests the models, invariants, and serialization.
"""

import tempfile
from pathlib import Path

import pytest
import yaml

from orgos import (
    Department,
    Org,
    SOP,
    PermissionTier,
    RoleSpec,
    TaskBrief,
    load_org,
)
from orgos.tools import BashTool


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def worker():
    return RoleSpec(
        name="test-worker",
        description="A worker.",
        tier=PermissionTier.WORKER,
        system_prompt="Do work.",
        model="gpt-4o-mini",
    )


@pytest.fixture
def supervisor():
    return RoleSpec(
        name="test-supervisor",
        description="A supervisor.",
        tier=PermissionTier.ORCHESTRATOR,
        system_prompt="Delegate work.",
        model="gpt-4o-mini",
        allow_delegation=True,
    )


@pytest.fixture
def sample_org_yaml():
    return """
org:
  name: TestOrg
  default_model: gpt-4o-mini
  owner:
    name: Tester
    preferences: Test preferences.
  notification:
    type: terminal

departments:
  - name: engineering
    description: Builds things.
    supervisor:
      name: eng-lead
      tier: orchestrator
      system_prompt: Lead the team.
      model: gpt-4o
      max_iter: 15
    members:
      - name: developer
        tier: worker
        system_prompt: Write code.
        model: gpt-4o-mini
      - name: reviewer
        tier: validator
        system_prompt: Review code.
        model: gpt-4o-mini
    shared_skills:
      - ./skills/coding
    sops:
      - name: daily_build
        cadence: daily
        brief:
          objective: Run the daily build.
"""


# ── Department invariants ──────────────────────────────────────────────────


class TestDepartmentInvariants:
    def test_supervisor_must_be_orchestrator(self, worker):
        with pytest.raises(ValueError, match="orchestrator"):
            Department(name="bad", supervisor=worker)

    def test_auto_sets_allow_delegation(self, supervisor):
        dept = Department(name="test", supervisor=supervisor)
        assert dept.supervisor.allow_delegation is True

    def test_all_roles_includes_supervisor_first(self, supervisor, worker):
        dept = Department(name="test", supervisor=supervisor, members=[worker])
        roles = dept.all_roles()
        assert len(roles) == 2
        assert roles[0].name == "test-supervisor"
        assert roles[1].name == "test-worker"

    def test_empty_members(self, supervisor):
        dept = Department(name="solo", supervisor=supervisor)
        roles = dept.all_roles()
        assert len(roles) == 1
        assert roles[0].name == "test-supervisor"


# ── Role enrichment ───────────────────────────────────────────────────────


class TestRoleEnrichment:
    def test_shared_skills_merged(self, supervisor, worker):
        dept = Department(
            name="test", supervisor=supervisor, members=[worker],
            shared_skills=["./skills/cointegration"],
        )
        enriched = dept._enrich_role(worker)
        assert "./skills/cointegration" in enriched.skills

    def test_shared_mcps_merged(self, supervisor, worker):
        mcp = {"type": "stdio", "command": "python"}
        dept = Department(
            name="test", supervisor=supervisor, members=[worker],
            shared_mcps=[mcp],
        )
        enriched = dept._enrich_role(worker)
        assert mcp in enriched.mcp_servers

    def test_no_duplicate_skills(self, supervisor, worker):
        """Shared skills should not duplicate existing role skills."""
        worker_with_skill = worker.model_copy(
            update={"skills": ["./skills/cointegration"]}
        )
        dept = Department(
            name="test", supervisor=supervisor, members=[worker_with_skill],
            shared_skills=["./skills/cointegration"],
        )
        enriched = dept._enrich_role(worker_with_skill)
        assert enriched.skills.count("./skills/cointegration") == 1

    def test_original_role_not_mutated(self, supervisor, worker):
        original_skills = list(worker.skills)
        dept = Department(
            name="test", supervisor=supervisor, members=[worker],
            shared_skills=["./skills/trading"],
        )
        dept._enrich_role(worker)
        # Original should be untouched
        assert worker.skills == original_skills


# ── SOPs ───────────────────────────────────────────────────────────────────


class TestSOPs:
    def test_find_sop(self, supervisor):
        sop = SOP(
            name="morning_scan",
            brief=TaskBrief(objective="Scan"),
            cadence="daily",
        )
        dept = Department(name="test", supervisor=supervisor, sops=[sop])
        found = dept.find_sop("morning_scan")
        assert found is not None
        assert found.cadence == "daily"

    def test_find_sop_missing(self, supervisor):
        dept = Department(name="test", supervisor=supervisor, sops=[])
        assert dept.find_sop("nonexistent") is None

    def test_sop_without_cadence(self, supervisor):
        sop = SOP(name="adhoc", brief=TaskBrief(objective="Do something"))
        dept = Department(name="test", supervisor=supervisor, sops=[sop])
        assert dept.find_sop("adhoc").cadence is None


# ── Org model ──────────────────────────────────────────────────────────────


class TestOrg:
    def test_find_department(self, supervisor):
        dept = Department(name="finance", supervisor=supervisor)
        org = Org(name="TestCorp", departments=[dept])
        assert org.find_department("finance") is not None
        assert org.find_department("marketing") is None

    def test_all_roles_flat(self, supervisor, worker):
        dept = Department(name="eng", supervisor=supervisor, members=[worker])
        org = Org(name="TestCorp", departments=[dept])
        flat = org.all_roles()
        assert len(flat) == 2
        assert ("eng", supervisor) in flat

    def test_default_values(self):
        org = Org(name="Minimal")
        assert org.default_model == "gpt-4o-mini"
        assert org.default_max_budget_tokens is None
        assert org.default_max_iter == 20
        assert org.departments == []

    def test_use_memory_creates_once(self, supervisor):
        dept = Department(name="test", supervisor=supervisor)
        org = Org(name="TestCorp", departments=[dept])
        db = tempfile.mktemp(suffix=".db")
        try:
            m1 = org.use_memory(db)
            m2 = org.use_memory(db)
            assert m1 is m2  # same instance
            m1.close()
        finally:
            Path(db).unlink(missing_ok=True)


# ── YAML loading ───────────────────────────────────────────────────────────


class TestYamlLoading:
    def test_load_org_from_yaml(self, sample_org_yaml):
        path = Path(tempfile.mktemp(suffix=".yaml"))
        path.write_text(sample_org_yaml)
        try:
            org = load_org(str(path))
            assert org.name == "TestOrg"
            assert org.owner.name == "Tester"
            assert org.owner.preferences == "Test preferences."
            assert len(org.departments) == 1
            eng = org.departments[0]
            assert eng.name == "engineering"
            assert eng.supervisor.name == "eng-lead"
            assert len(eng.members) == 2
            assert eng.members[0].name == "developer"
            assert eng.members[1].name == "reviewer"
            assert eng.shared_skills == ["./skills/coding"]
            assert len(eng.sops) == 1
            assert eng.sops[0].name == "daily_build"
            assert eng.sops[0].cadence == "daily"
        finally:
            path.unlink(missing_ok=True)

    def test_load_org_without_owner(self):
        """Owner is optional — defaults to OwnerProfile()."""
        yaml_str = """
org:
  name: BareOrg
departments: []
"""
        path = Path(tempfile.mktemp(suffix=".yaml"))
        path.write_text(yaml_str)
        try:
            org = load_org(str(path))
            assert org.name == "BareOrg"
            assert org.owner.name == "Owner"  # default
        finally:
            path.unlink(missing_ok=True)

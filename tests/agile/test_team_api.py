"""Tests for team API endpoints: /api/team/topology, /api/team/adrs,
/api/team/adrs/{id}/approve, /api/team/adrs/{id}/reject.

Uses FastAPI TestClient with isolated temp DBs and a stub org.yaml.
apply_adr is monkeypatched to a no-op so git-commit side effects
don't run in CI.
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _isolated_dbs(tmp_path, monkeypatch):
    """Point all storage at temp files and supply a minimal org.yaml."""
    mem_db = str(tmp_path / "memory.db")
    pm_db = str(tmp_path / "pm.db")
    monkeypatch.setenv("ORGOS_MEMORY_DB", mem_db)
    monkeypatch.setenv("ORGOS_PM_DB", pm_db)
    org_yaml = tmp_path / "org.yaml"
    org_yaml.write_text("org:\n  name: TestOrg\ndepartments: []\nhandoffs: []\n")
    monkeypatch.setenv("ORGOS_ORG_YAML", str(org_yaml))


@pytest.fixture()
def _org_yaml_with_dept(tmp_path, monkeypatch):
    """Write an org.yaml with one department so topology returns real data."""
    org_yaml = tmp_path / "org.yaml"
    org_yaml.write_text(
        "org:\n  name: TestOrg\n"
        "departments:\n"
        "  - name: engineering\n"
        "    supervisor:\n"
        "      name: sprint-lead\n"
        "      tier: orchestrator\n"
        "    members:\n"
        "      - name: engineer\n"
        "        tier: worker\n"
        "handoffs: []\n"
    )
    monkeypatch.setenv("ORGOS_ORG_YAML", str(org_yaml))
    return org_yaml


def _client():
    """Return a TestClient with deferred import so env vars are in effect."""
    # Re-import each time so module-level globals pick up monkeypatched env.
    import importlib
    import orgos.api as _api_mod
    importlib.reload(_api_mod)
    from fastapi.testclient import TestClient
    return TestClient(_api_mod.app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# /api/team/topology
# ---------------------------------------------------------------------------

class TestTopologyEndpoint:
    def test_empty_config_returns_200(self):
        c = _client()
        resp = c.get("/api/team/topology")
        assert resp.status_code == 200

    def test_empty_config_returns_empty_lists(self):
        c = _client()
        body = c.get("/api/team/topology").json()
        assert body == {"roles": [], "edges": []}

    def test_shape_with_department(self, _org_yaml_with_dept, tmp_path, monkeypatch):
        """With a real department in org.yaml, topology returns non-empty lists."""
        # _org_yaml_with_dept already monkeypatched ORGOS_ORG_YAML
        c = _client()
        body = c.get("/api/team/topology").json()
        assert "roles" in body
        assert "edges" in body
        assert isinstance(body["roles"], list)
        assert isinstance(body["edges"], list)
        # Supervisor + 1 member => 2 roles
        assert len(body["roles"]) == 2
        names = [r["name"] for r in body["roles"]]
        assert "sprint-lead" in names
        assert "engineer" in names

    def test_roles_have_required_keys(self, _org_yaml_with_dept):
        c = _client()
        body = c.get("/api/team/topology").json()
        for role in body["roles"]:
            assert "name" in role
            assert "tier" in role
            assert "contribution" in role

    def test_edges_connect_supervisor_to_members(self, _org_yaml_with_dept):
        c = _client()
        body = c.get("/api/team/topology").json()
        assert len(body["edges"]) >= 1
        edge = body["edges"][0]
        assert edge["from"] == "sprint-lead"
        assert edge["to"] == "engineer"
        assert "weight" in edge


# ---------------------------------------------------------------------------
# /api/team/adrs
# ---------------------------------------------------------------------------

class TestAdrListEndpoint:
    def test_empty_returns_200(self):
        c = _client()
        resp = c.get("/api/team/adrs")
        assert resp.status_code == 200

    def test_empty_returns_four_empty_lists(self):
        c = _client()
        body = c.get("/api/team/adrs").json()
        assert set(body.keys()) == {"pending", "approved", "applied", "rejected"}
        assert body["pending"] == []
        assert body["approved"] == []
        assert body["applied"] == []
        assert body["rejected"] == []

    def test_pending_adr_appears_in_pending_group(self):
        import orgos.api as _api_mod
        import importlib
        importlib.reload(_api_mod)
        from fastapi.testclient import TestClient
        from orgos.pm import PMStore as _PMStore
        import os

        with TestClient(_api_mod.app, raise_server_exceptions=True) as c:
            assert _api_mod.pm is not None
            aid = _api_mod.pm.create_adr(
                sprint_id="s1", kind="ADD_ROLE",
                before_yaml="before", after_yaml="after",
                rationale="test pending",
            )
            body = c.get("/api/team/adrs").json()

        assert any(a["id"] == aid for a in body["pending"])
        assert body["approved"] == []


# ---------------------------------------------------------------------------
# /api/team/adrs/{id}/approve
# ---------------------------------------------------------------------------

class TestAdrApproveEndpoint:
    def test_approve_flips_status_to_applied(self, monkeypatch):
        """POST approve -> ADR moves to applied; apply_adr is monkeypatched."""
        import orgos.api as _api_mod
        import orgos.evolve as _evolve_mod
        import importlib
        importlib.reload(_api_mod)

        applied_ids: list[int] = []

        def _fake_apply_adr(pm, adr_id, **kwargs):
            # Simulate what apply_adr does: set status to applied
            pm.set_adr_status(adr_id, "applied")
            applied_ids.append(adr_id)

        monkeypatch.setattr(_evolve_mod, "apply_adr", _fake_apply_adr)
        # Also patch the reference in api module after reload
        monkeypatch.setattr("orgos.evolve.apply_adr", _fake_apply_adr)

        from fastapi.testclient import TestClient
        with TestClient(_api_mod.app, raise_server_exceptions=True) as c:
            assert _api_mod.pm is not None
            aid = _api_mod.pm.create_adr(
                sprint_id="s1", kind="ADD_ROLE",
                before_yaml="before", after_yaml="after",
                rationale="approve test",
            )
            resp = c.post(f"/api/team/adrs/{aid}/approve")
            assert resp.status_code == 200
            body = resp.json()
            assert body["ok"] is True
            assert body["id"] == aid
            # apply_adr was called
            assert aid in applied_ids

    def test_approve_nonexistent_returns_error(self, monkeypatch):
        """Approving an ADR that doesn't exist should raise (500 or 404)."""
        import orgos.api as _api_mod
        import orgos.evolve as _evolve_mod
        import importlib
        importlib.reload(_api_mod)

        def _fake_apply_adr(pm, adr_id, **kwargs):
            raise ValueError(f"ADR {adr_id} not found")

        monkeypatch.setattr(_evolve_mod, "apply_adr", _fake_apply_adr)
        monkeypatch.setattr("orgos.evolve.apply_adr", _fake_apply_adr)

        from fastapi.testclient import TestClient
        with TestClient(_api_mod.app, raise_server_exceptions=False) as c:
            resp = c.post("/api/team/adrs/9999/approve")
            assert resp.status_code in (404, 500)


# ---------------------------------------------------------------------------
# /api/team/adrs/{id}/reject
# ---------------------------------------------------------------------------

class TestAdrRejectEndpoint:
    def test_reject_flips_status_to_rejected(self):
        import orgos.api as _api_mod
        import importlib
        importlib.reload(_api_mod)

        from fastapi.testclient import TestClient
        with TestClient(_api_mod.app, raise_server_exceptions=True) as c:
            assert _api_mod.pm is not None
            aid = _api_mod.pm.create_adr(
                sprint_id="s1", kind="REMOVE_ROLE",
                before_yaml="before", after_yaml="after",
                rationale="reject test",
            )
            resp = c.post(f"/api/team/adrs/{aid}/reject")
            assert resp.status_code == 200
            body = resp.json()
            assert body["ok"] is True
            assert body["id"] == aid
            assert body["status"] == "rejected"
            # Verify in DB
            adrs = _api_mod.pm.list_adrs(status="rejected")
            assert any(a["id"] == aid for a in adrs)

    def test_reject_returns_correct_shape(self):
        import orgos.api as _api_mod
        import importlib
        importlib.reload(_api_mod)

        from fastapi.testclient import TestClient
        with TestClient(_api_mod.app, raise_server_exceptions=True) as c:
            assert _api_mod.pm is not None
            aid = _api_mod.pm.create_adr(
                "s1", "REMOVE_ROLE", "b", "a", "shape test",
            )
            body = c.post(f"/api/team/adrs/{aid}/reject").json()
            assert "ok" in body
            assert "id" in body
            assert "status" in body

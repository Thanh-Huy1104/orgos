"""Tests for lab API endpoints: POST /api/lab/replay + GET /api/sprints/{id}.

Uses FastAPI TestClient with isolated temp DBs.
replay_sprint is monkeypatched for the happy-path test so no real agent spawn
or git operations are required.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _client(monkeypatch, tmp_path):
    """Return a TestClient reloading api so env vars take effect."""
    import importlib
    import orgos.api as _api_mod
    importlib.reload(_api_mod)
    from fastapi.testclient import TestClient
    return TestClient(_api_mod.app, raise_server_exceptions=True)


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    """Point all storage at temp dirs and supply a minimal org.yaml."""
    # Create _orgos_memory so ProposalStore (which uses a relative path) can open.
    (tmp_path / "_orgos_memory").mkdir(exist_ok=True)
    mem_db = str(tmp_path / "memory.db")
    pm_db = str(tmp_path / "pm.db")
    monkeypatch.setenv("ORGOS_MEMORY_DB", mem_db)
    monkeypatch.setenv("ORGOS_PM_DB", pm_db)
    org_yaml = tmp_path / "org.yaml"
    org_yaml.write_text("org:\n  name: TestOrg\ndepartments: []\nhandoffs: []\n")
    monkeypatch.setenv("ORGOS_ORG_YAML", str(org_yaml))
    # Make the cwd the tmp_path so relative paths inside replay_sprint resolve.
    monkeypatch.chdir(tmp_path)


# ---------------------------------------------------------------------------
# GET /api/sprints/{sprint_id}
# ---------------------------------------------------------------------------

class TestGetSprintEndpoint:
    def test_unknown_sprint_returns_not_found(self, tmp_path, monkeypatch):
        c = _client(monkeypatch, tmp_path)
        resp = c.get("/api/sprints/does-not-exist")
        assert resp.status_code == 200
        assert resp.json() == {"error": "not_found"}

    def test_existing_sprint_returns_shape(self, tmp_path, monkeypatch):
        import importlib
        import orgos.api as _api_mod
        importlib.reload(_api_mod)
        from fastapi.testclient import TestClient
        from orgos.pm import PMStore

        pm_db = str(tmp_path / "pm.db")
        seed_pm = PMStore(pm_db)
        seed_pm.create_sprint("s-123", "agile/s-123", {"issue_id": "7"}, "completed")
        seed_pm.close()

        with TestClient(_api_mod.app, raise_server_exceptions=True) as c:
            resp = c.get("/api/sprints/s-123")
        assert resp.status_code == 200
        body = resp.json()
        assert "sprint" in body
        assert "envelopes" in body
        assert "replay" in body
        assert body["sprint"]["id"] == "s-123"
        assert body["replay"] is None  # no _replay envelope

    def test_sprint_with_replay_envelope_returns_replay(self, tmp_path, monkeypatch):
        import importlib
        import orgos.api as _api_mod
        importlib.reload(_api_mod)
        from fastapi.testclient import TestClient
        from orgos.pm import PMStore

        pm_db = str(tmp_path / "pm.db")
        seed_pm = PMStore(pm_db)
        seed_pm.create_sprint("s-456", "agile/s-456", {"issue_id": "8"}, "completed")
        replay_data = {"parent_sprint_id": "s-orig", "mutation_kind": "inject_heuristic",
                       "mutation": {"rule": "x", "why": "y", "tags": [], "kind": "inject_heuristic"}}
        seed_pm.record_sprint_envelope("s-456", "_replay", json.dumps(replay_data))
        seed_pm.close()

        with TestClient(_api_mod.app, raise_server_exceptions=True) as c:
            resp = c.get("/api/sprints/s-456")
        assert resp.status_code == 200
        body = resp.json()
        assert body["replay"] is not None
        assert body["replay"]["parent_sprint_id"] == "s-orig"
        assert body["replay"]["mutation_kind"] == "inject_heuristic"


# ---------------------------------------------------------------------------
# POST /api/lab/replay
# ---------------------------------------------------------------------------

class TestLabReplayEndpoint:
    def test_unknown_mutation_kind_returns_error(self, tmp_path, monkeypatch):
        c = _client(monkeypatch, tmp_path)
        resp = c.post("/api/lab/replay", json={
            "parent_sprint_id": "any",
            "mutation_kind": "unknown_kind",
            "mutation_args": {},
        })
        assert resp.status_code == 200
        assert resp.json() == {"error": "unknown mutation_kind: unknown_kind"}

    def test_nonexistent_parent_sprint_errors_cleanly(self, tmp_path, monkeypatch):
        """replay_sprint raises FileNotFoundError for missing snapshot;
        the endpoint catches it and returns a JSON error."""
        c = _client(monkeypatch, tmp_path)
        resp = c.post("/api/lab/replay", json={
            "parent_sprint_id": "ghost-sprint",
            "mutation_kind": "inject_heuristic",
            "mutation_args": {"rule": "x", "why": "y"},
        })
        # Either 200 with error field or 500 — both acceptable.
        # The important thing is the server does not crash unhandled.
        assert resp.status_code in (200, 500)
        if resp.status_code == 200:
            body = resp.json()
            assert "error" in body

    def test_replay_with_seeded_snapshot_returns_replay_sprint_id(
        self, tmp_path, monkeypatch
    ):
        """Seed a snapshot + PMStore row, then POST replay; verify replay_sprint_id
        is returned. replay_sprint is called with _offline=True via monkeypatch."""
        import importlib
        import orgos.api as _api_mod
        import orgos.agile.replay as _replay_mod
        from orgos.agile.sprint import Sprint, write_snapshot
        from orgos.pm import PMStore

        pm_db = str(tmp_path / "pm.db")

        # Seed parent sprint in PMStore.
        seed_pm = PMStore(pm_db)
        seed_pm.create_sprint(
            "parent-1", "agile/parent-1", {"issue_id": "1"}, "completed",
        )
        seed_pm.close()

        # Write snapshot to disk.
        (tmp_path / ".sprints" / "parent-1").mkdir(parents=True)
        parent_sprint = Sprint(
            id="parent-1",
            started_at="2026-07-01T00:00:00Z",
            repo_path=tmp_path,
            worktree_path=tmp_path / ".sprints" / "parent-1",
            branch="agile/parent-1",
            picked_issue={"issue_id": "1", "title": "fix bug", "labels": [],
                          "body": "desc", "url": "http://x"},
            envelopes={},
            status="completed",
        )
        write_snapshot(
            parent_sprint,
            backlog=[{"issue_id": "1", "title": "fix bug", "labels": [],
                      "body": "desc", "url": "http://x"}],
            heuristics=[],
        )

        # Monkeypatch replay_sprint to use _offline=True to avoid git + LLM calls.
        original_replay = _replay_mod.replay_sprint

        def _fast_replay(parent_sprint_id, mutation, **kwargs):
            return original_replay(
                parent_sprint_id, mutation, base_dir=tmp_path, _offline=True,
            )

        monkeypatch.setattr(_replay_mod, "replay_sprint", _fast_replay)
        # Also patch the reference imported into api.py at call time
        # (api.py uses `from orgos.agile.replay import replay_sprint` inside the handler,
        # so we patch the module attribute directly).
        monkeypatch.setattr("orgos.agile.replay.replay_sprint", _fast_replay)

        importlib.reload(_api_mod)
        from fastapi.testclient import TestClient
        with TestClient(_api_mod.app, raise_server_exceptions=True) as c:
            resp = c.post("/api/lab/replay", json={
                "parent_sprint_id": "parent-1",
                "mutation_kind": "inject_heuristic",
                "mutation_args": {"rule": "always test", "why": "quality"},
            })

        assert resp.status_code == 200
        body = resp.json()
        assert "replay_sprint_id" in body
        assert body["replay_sprint_id"] != "parent-1"
        assert "status" in body
        assert "picked_issue" in body

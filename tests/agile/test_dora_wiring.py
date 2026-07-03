"""Tests for DORA wiring: /api/dora + /api/heuristics endpoints.

We use FastAPI TestClient to verify the endpoints return 200 and the expected
{latest, history} / {active, candidates} shape without requiring a live LLM
or a real sprint run.
"""
from __future__ import annotations

import os
import tempfile

import pytest

# Point storage at isolated temp files so tests don't touch real DBs.
@pytest.fixture(autouse=True)
def _isolated_dbs(tmp_path, monkeypatch):
    mem_db = str(tmp_path / "memory.db")
    pm_db = str(tmp_path / "pm.db")
    monkeypatch.setenv("ORGOS_MEMORY_DB", mem_db)
    monkeypatch.setenv("ORGOS_PM_DB", pm_db)
    # Stub out org.yaml so lifespan doesn't fail.
    org_yaml = tmp_path / "org.yaml"
    org_yaml.write_text("org:\n  name: TestOrg\ndepartments: []\nhandoffs: []\n")
    monkeypatch.setenv("ORGOS_ORG_YAML", str(org_yaml))


def _client():
    """Return a TestClient wrapping orgos.api.app.

    Import is deferred so env vars set by the fixture take effect.
    """
    from fastapi.testclient import TestClient
    from orgos.api import app
    return TestClient(app, raise_server_exceptions=True)


class TestDoraEndpoint:
    def test_returns_200(self):
        c = _client()
        resp = c.get("/api/dora")
        assert resp.status_code == 200

    def test_shape_with_empty_db(self):
        c = _client()
        resp = c.get("/api/dora")
        body = resp.json()
        assert "latest" in body
        assert "history" in body
        assert isinstance(body["history"], list)

    def test_latest_has_tier(self):
        c = _client()
        body = c.get("/api/dora").json()
        latest = body["latest"]
        assert "tier" in latest
        assert latest["tier"] in ("Elite", "High", "Medium", "Low")

    def test_window_param_accepted(self):
        c = _client()
        resp = c.get("/api/dora?window=7&limit=10")
        assert resp.status_code == 200

    def test_history_reflects_stored_snapshots(self):
        """Store a snapshot via the lifespan pm object (shared connection),
        then verify it appears in the /api/dora history."""
        import orgos.api as _api
        from fastapi.testclient import TestClient
        from orgos.api import app

        with TestClient(app) as c:
            # _api.pm is now live (lifespan ran). Write through it so the
            # endpoint's "pm if pm is not None" branch reads the same rows.
            assert _api.pm is not None, "lifespan pm should be set"
            _api.pm.record_dora_snapshot({
                "window_days": 14, "deploy_freq": 2.0,
                "lead_time_p50": 3600.0, "cfr": 0.02, "mttr_p50": 900.0,
                "tier": "Elite",
            })
            body = c.get("/api/dora").json()

        assert len(body["history"]) >= 1
        tiers = [r["tier"] for r in body["history"]]
        assert "Elite" in tiers
        assert body["latest"]["tier"] == "Elite"


class TestHeuristicsEndpoint:
    def test_returns_200(self):
        c = _client()
        resp = c.get("/api/heuristics")
        assert resp.status_code == 200

    def test_shape_with_empty_db(self):
        c = _client()
        body = c.get("/api/heuristics").json()
        assert "active" in body
        assert "candidates" in body
        assert isinstance(body["active"], list)
        assert isinstance(body["candidates"], list)

    def test_candidate_heuristics_appear(self):
        """Heuristics stored with use_count=0 should appear in candidates."""
        from orgos.reflect import Reflector, Heuristic
        import uuid
        from datetime import datetime, timezone

        r = Reflector(domain="agile")
        h = Heuristic(
            id=f"dora-{uuid.uuid4().hex[:8]}",
            domain="agile",
            tags=["test"],
            rule="Test rule — candidate",
            why="unit test",
            source_run_id=None,
            score=0.5,
            use_count=0,
            created_at=datetime.now(timezone.utc).isoformat(),
            source="dora",
        )
        r._store(h)

        c = _client()
        body = c.get("/api/heuristics").json()
        ids = [x["id"] for x in body["candidates"]]
        assert h.id in ids
        # Should NOT be in active
        active_ids = [x["id"] for x in body["active"]]
        assert h.id not in active_ids

    def test_active_heuristics_appear(self):
        """Heuristics with use_count > 0 should appear in active."""
        from orgos.reflect import Reflector, Heuristic
        import uuid
        from datetime import datetime, timezone

        r = Reflector(domain="agile")
        h = Heuristic(
            id=f"dora-{uuid.uuid4().hex[:8]}",
            domain="agile",
            tags=["test"],
            rule="Test rule — active",
            why="unit test",
            source_run_id=None,
            score=0.8,
            use_count=3,
            created_at=datetime.now(timezone.utc).isoformat(),
            source="dora",
        )
        r._store(h)

        c = _client()
        body = c.get("/api/heuristics").json()
        active_ids = [x["id"] for x in body["active"]]
        assert h.id in active_ids
        candidate_ids = [x["id"] for x in body["candidates"]]
        assert h.id not in candidate_ids


class TestDoraSprintWiringUnit:
    """Unit-test the DORA→heuristic bridge without an LLM."""

    def test_dora_to_heuristic_candidates_low_deploy(self):
        """Low deploy frequency should produce an engineer heuristic."""
        from orgos.agile.dora_bridge import dora_to_heuristic_candidates

        snapshot = {
            "window_days": 14,
            "deploy_freq": 0.05,   # below 0.14 threshold
            "lead_time_p50": 86400.0,
            "cfr": 0.02,
            "mttr_p50": 3600.0,
            "tier": "Medium",
        }
        candidates = dora_to_heuristic_candidates(None, snapshot)
        tags_flat = [tag for h in candidates for tag in h.tags]
        assert "engineer" in tags_flat

    def test_dora_to_heuristic_candidates_high_lead_time(self):
        """Lead time > 7 days should produce a pm heuristic."""
        from orgos.agile.dora_bridge import dora_to_heuristic_candidates

        snapshot = {
            "window_days": 14,
            "deploy_freq": 1.5,
            "lead_time_p50": 9 * 86400.0,  # > 7d threshold
            "cfr": 0.02,
            "mttr_p50": 3600.0,
            "tier": "Low",
        }
        candidates = dora_to_heuristic_candidates(None, snapshot)
        tags_flat = [tag for h in candidates for tag in h.tags]
        assert "pm" in tags_flat

    def test_dora_to_heuristic_candidates_high_mttr(self):
        """MTTR > 4h should produce a qa heuristic."""
        from orgos.agile.dora_bridge import dora_to_heuristic_candidates

        snapshot = {
            "window_days": 14,
            "deploy_freq": 1.5,
            "lead_time_p50": 3600.0,
            "cfr": 0.02,
            "mttr_p50": 5 * 3600.0,  # > 4h threshold
            "tier": "Low",
        }
        candidates = dora_to_heuristic_candidates(None, snapshot)
        tags_flat = [tag for h in candidates for tag in h.tags]
        assert "qa" in tags_flat

    def test_heuristic_candidates_have_required_fields(self):
        from orgos.agile.dora_bridge import dora_to_heuristic_candidates

        snapshot = {
            "window_days": 14,
            "deploy_freq": 0.05,
            "lead_time_p50": 10 * 86400.0,
            "cfr": 0.02,
            "mttr_p50": 6 * 3600.0,
            "tier": "Low",
        }
        candidates = dora_to_heuristic_candidates(None, snapshot)
        assert len(candidates) >= 1
        for h in candidates:
            assert h.id.startswith("dora-")
            assert h.domain == "agile"
            assert h.use_count == 0
            assert h.source == "dora"
            assert h.rule

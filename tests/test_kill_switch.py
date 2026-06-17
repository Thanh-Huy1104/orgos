"""Tests for the kill switch (offline — Redis + icarus_db + EDGAR all mocked)."""

import pytest

from orgos import kill_switch as ks


class FakeRedis:
    """Minimal in-memory Redis stand-in capturing set/get."""
    def __init__(self):
        self.store = {}
        self.closed = False
        self.deletes = 0

    def get(self, k):
        return self.store.get(k)

    def set(self, k, v):
        self.store[k] = v

    def delete(self, k):
        self.deletes += 1
        self.store.pop(k, None)

    def close(self):
        self.closed = True


@pytest.fixture
def fake_redis(monkeypatch):
    r = FakeRedis()
    monkeypatch.setattr(ks, "_redis_client", lambda: r)
    return r


def _filings(*forms):
    return [{"form": f, "date": "2026-06-01", "primary_doc": "", "accession": ""}
            for f in forms]


class TestPublishHalt:
    def test_sets_halt_value(self, fake_redis):
        out = ks.publish_halt(2, "structural break on XOM")
        assert fake_redis.store["risk:structural_break:2"] == "1"
        assert out["halted"] is True and out["pair_id"] == 2

    def test_is_set_only_never_deletes(self, fake_redis):
        # The module must expose no clear/un-halt path that deletes the key.
        ks.publish_halt(1, "x")
        assert fake_redis.deletes == 0
        assert not hasattr(ks, "clear_halt")   # no un-halt function exists


class TestHaltState:
    def test_reads_per_pair(self, fake_redis, monkeypatch):
        monkeypatch.setattr(ks.icarus_db, "active_pairs",
                            lambda: [{"pair_id": 1, "pair": "V/MA", "y": "V", "x": "MA"},
                                     {"pair_id": 2, "pair": "XOM/CVX", "y": "XOM", "x": "CVX"}])
        fake_redis.store["risk:structural_break:2"] = "1"   # pair 2 halted
        state = ks.halt_state()
        assert state == {1: False, 2: True}


class TestAssessActivePairs:
    def _pairs(self):
        return [{"pair_id": 1, "pair": "V/MA", "y": "V", "x": "MA"},
                {"pair_id": 2, "pair": "XOM/CVX", "y": "XOM", "x": "CVX"}]

    def test_high_risk_leg_recommends_halt(self, fake_redis, monkeypatch):
        monkeypatch.setattr(ks.icarus_db, "active_pairs", self._pairs)
        # XOM has a merger filing (HIGH); everything else routine.
        monkeypatch.setattr(ks, "recent_filings",
                            lambda leg, days=30: _filings("425") if leg == "XOM" else _filings("10-Q"))
        out = ks.assess_active_pairs()
        halts = {a["pair"] for a in out["recommend_halt"]}
        assert halts == {"XOM/CVX"}
        assert "1 recommended for halt" in out["summary"]

    def test_already_halted_not_recommended_again(self, fake_redis, monkeypatch):
        monkeypatch.setattr(ks.icarus_db, "active_pairs", self._pairs)
        monkeypatch.setattr(ks, "recent_filings",
                            lambda leg, days=30: _filings("425") if leg == "XOM" else _filings("10-Q"))
        fake_redis.store["risk:structural_break:2"] = "1"   # already halted
        out = ks.assess_active_pairs()
        assert out["recommend_halt"] == []                  # not re-recommended
        assert any(a["already_halted"] for a in out["active_pairs"])

    def test_clean_book_no_recommendations(self, fake_redis, monkeypatch):
        monkeypatch.setattr(ks.icarus_db, "active_pairs", self._pairs)
        monkeypatch.setattr(ks, "recent_filings", lambda leg, days=30: _filings("10-Q"))
        out = ks.assess_active_pairs()
        assert out["recommend_halt"] == []

    def test_redis_down_still_assesses_sec(self, monkeypatch):
        # Redis unreachable → halt_state raises → assessment still returns SEC view.
        monkeypatch.setattr(ks.icarus_db, "active_pairs", self._pairs)
        monkeypatch.setattr(ks, "recent_filings", lambda leg, days=30: _filings("10-Q"))

        def boom():
            raise RuntimeError("redis down")
        monkeypatch.setattr(ks, "halt_state", boom)
        out = ks.assess_active_pairs()
        assert len(out["active_pairs"]) == 2     # didn't crash


class TestRedisConfig:
    def test_falls_back_to_icarus_env(self, monkeypatch, tmp_path):
        for k in ("REDIS_HOST", "REDIS_PORT", "REDIS_USER", "REDIS_PASSWORD"):
            monkeypatch.delenv(k, raising=False)
        env = tmp_path / ".env"
        env.write_text("REDIS_HOST=192.168.5.60\nREDIS_PORT=6379\nREDIS_USER=appuser\nREDIS_PASSWORD=sekret\n")
        monkeypatch.setattr(ks, "ICARUS_PATH", tmp_path)
        cfg = ks._redis_config()
        assert cfg["host"] == "192.168.5.60" and cfg["username"] == "appuser"
        assert cfg["port"] == 6379

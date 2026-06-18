"""Tests for the research journal (memory) — offline, temp SQLite."""

import json

import pytest

from orgos import quant_journal as jr
from orgos.tools import research_sources as rs


class TestJournal:
    def test_record_and_recent_newest_first(self, tmp_path):
        db = str(tmp_path / "j.db")
        jr.record("utilities scan", "found AEE/NI", status="completed", tokens=100, db_path=db)
        jr.record("banks scan", "no durable pairs", status="completed", tokens=200, db_path=db)
        rows = jr.recent(5, db_path=db)
        assert len(rows) == 2
        assert rows[0]["objective"] == "banks scan"          # newest first
        assert rows[1]["summary"] == "found AEE/NI"

    def test_recent_limit(self, tmp_path):
        db = str(tmp_path / "j.db")
        for i in range(10):
            jr.record(f"run {i}", f"finding {i}", db_path=db)
        assert len(jr.recent(3, db_path=db)) == 3

    def test_prior_block_empty_on_fresh_journal(self, tmp_path):
        assert jr.prior_research_block(db_path=str(tmp_path / "empty.db")) == ""

    def test_prior_block_formats_entries(self, tmp_path):
        db = str(tmp_path / "j.db")
        jr.record("utilities", "AEE/NI durable, hl 8d; cross-sector dead end", db_path=db)
        block = jr.prior_research_block(db_path=db)
        assert "Prior research notes" in block
        assert "AEE/NI durable" in block

    def test_prior_block_trims_long_summaries(self, tmp_path):
        db = str(tmp_path / "j.db")
        jr.record("x", "y" * 5000, db_path=db)
        block = jr.prior_research_block(max_chars=200, db_path=db)
        assert block.count("y") <= 220                       # trimmed


class TestNewsCatalysts:
    def test_parses_tavily_news(self, monkeypatch):
        class FakeResp:
            def raise_for_status(self): pass
            def json(self):
                return {"results": [
                    {"title": "Utility merger announced", "url": "http://x", "content": "DUK to acquire..."},
                    {"title": "Refining margins spike", "url": "http://y", "content": "crack spreads..."},
                ]}

        import httpx
        monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
        monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeResp())
        news = rs.search_news("utility mergers")
        assert len(news) == 2 and news[0]["title"] == "Utility merger announced"

    def test_no_key_raises(self, monkeypatch):
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        out = json.loads(rs.NewsCatalystTool()._run("x"))
        assert "error" in out                                # surfaced, not crashed

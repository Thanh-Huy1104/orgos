"""Tests for the research-grounding tools (offline — httpx/read_html mocked)."""

import json

import pandas as pd
import pytest

from orgos import research_sources as rs


class TestArxiv:
    def test_parses_entries(self, monkeypatch):
        atom = """
        <feed>
          <entry><title>Cointegration in Pairs Trading</title>
            <summary>We document a stable relationship between X and Y.</summary>
            <id>http://arxiv.org/abs/1234.5678</id>
            <published>2025-03-01T00:00:00Z</published></entry>
          <entry><title>Stat Arb in Crypto</title>
            <summary>Mean reversion among majors.</summary>
            <id>http://arxiv.org/abs/2345.6789</id>
            <published>2026-01-15T00:00:00Z</published></entry>
        </feed>"""

        class FakeResp:
            text = atom
            def raise_for_status(self): pass

        import httpx
        monkeypatch.setattr(httpx, "get", lambda *a, **k: FakeResp())
        papers = rs.search_arxiv("cointegration", 5)
        assert len(papers) == 2
        assert papers[0]["title"] == "Cointegration in Pairs Trading"
        assert papers[0]["url"].endswith("1234.5678")
        assert papers[1]["published"] == "2026-01-15"

    def test_tool_swallows_error(self, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("arxiv down")
        monkeypatch.setattr(rs, "search_arxiv", boom)
        out = json.loads(rs.ArxivSearchTool()._run("x"))
        assert "error" in out


class TestConstituents:
    def _fake_table(self):
        return pd.DataFrame({
            "Symbol": ["DUK", "SO", "AEP", "JPM", "BAC", "BRK.B"],
            "GICS Sector": ["Utilities", "Utilities", "Utilities",
                            "Financials", "Financials", "Financials"],
        })

    def test_filters_by_sector(self, monkeypatch):
        monkeypatch.setattr(rs, "_sp500_table", self._fake_table)
        out = rs.sp500_constituents("Utilities")
        assert out["count"] == 3
        assert set(out["tickers"]) == {"DUK", "SO", "AEP"}

    def test_case_insensitive_and_ticker_normalization(self, monkeypatch):
        monkeypatch.setattr(rs, "_sp500_table", self._fake_table)
        out = rs.sp500_constituents("financials")     # lowercase
        assert "BRK-B" in out["tickers"]               # BRK.B → BRK-B (Tiingo style)

    def test_empty_returns_all_plus_sector_list(self, monkeypatch):
        monkeypatch.setattr(rs, "_sp500_table", self._fake_table)
        out = rs.sp500_constituents("")
        assert out["count"] == 6
        assert "Utilities" in out["available_sectors"] and "Financials" in out["available_sectors"]

    def test_tool_returns_json(self, monkeypatch):
        monkeypatch.setattr(rs, "_sp500_table", self._fake_table)
        out = json.loads(rs.IndexConstituentsTool()._run("Utilities"))
        assert out["tickers"] == ["DUK", "SO", "AEP"]

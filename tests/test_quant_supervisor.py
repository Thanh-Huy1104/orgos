"""Tests for the recommend-only quant supervisor (offline — deps injected)."""

import pytest

from orgos.subagents import quant_supervisor


def _dossier(pair, verdict):
    return {"pair": pair, "verdict": verdict, "structural_risk": "LOW",
            "reasons": [], "stats": {}, "leg_filings": {}}


def _overview(active_pairs=None, equity=1_000_000.0):
    return {
        "account": {"total_equity": equity, "available_funds": equity,
                    "open_positions": 0, "as_of": "2026-06-17T00:00:00"},
        "active_pairs": active_pairs or [],
        "performance": {"closed_trades": 10, "wins": 6, "win_rate": 0.6,
                        "total_realized_pnl": 1234.0, "avg_pnl_per_trade": 123.4},
    }


def _make_scanner(by_universe):
    def scan(uni, **kw):
        cands = by_universe.get(uni, [])
        return {"universe": uni, "candidates": cands} if cands else {"candidates": []}
    return scan


def _make_screener(verdicts):
    """verdicts: pair -> verdict. screen returns grouped dossiers."""
    def screen(cands, **kw):
        out = {"promote": [], "review": [], "hold": []}
        for c in cands:
            v = verdicts.get(c["pair"], "PROMOTE")
            out[v.lower()].append(_dossier(c["pair"], v))
        return out
    return screen


class TestRecommend:
    def test_clean_new_pair_is_proposed(self):
        scanner = _make_scanner({"utilities": [{"pair": "DTE/SO", "y": "DTE", "x": "SO"}]})
        screener = _make_screener({"DTE/SO": "PROMOTE"})
        out = quant_supervisor.recommend(
            ["utilities"], scanner=scanner, screener=screener, overview=_overview)
        assert [d["pair"] for d in out["propose_spawn"]] == ["DTE/SO"]
        assert "DTE/SO" in out["summary"]

    def test_held_promote_not_reproposed(self):
        scanner = _make_scanner({"utilities": [{"pair": "DTE/SO", "y": "DTE", "x": "SO"}]})
        screener = _make_screener({"DTE/SO": "PROMOTE"})
        ov = lambda: _overview(active_pairs=[{"pair": "DTE/SO"}])
        out = quant_supervisor.recommend(
            ["utilities"], scanner=scanner, screener=screener, overview=ov)
        assert out["propose_spawn"] == []                    # already held
        assert [d["pair"] for d in out["promote_already_held"]] == ["DTE/SO"]

    def test_review_and_hold_not_proposed(self):
        scanner = _make_scanner({"banks": [
            {"pair": "JPM/BAC", "y": "JPM", "x": "BAC"},
            {"pair": "GS/MS", "y": "GS", "x": "MS"}]})
        screener = _make_screener({"JPM/BAC": "REVIEW", "GS/MS": "HOLD"})
        out = quant_supervisor.recommend(
            ["banks"], scanner=scanner, screener=screener, overview=_overview)
        assert out["propose_spawn"] == []
        assert len(out["review"]) == 1 and len(out["hold"]) == 1

    def test_empty_scan_skipped(self):
        scanner = _make_scanner({})                          # no candidates anywhere
        out = quant_supervisor.recommend(
            ["utilities", "banks"], scanner=scanner,
            screener=_make_screener({}), overview=_overview)
        assert out["propose_spawn"] == []
        assert "0 new pair(s)" in out["summary"]

    def test_multiple_universes_aggregated(self):
        scanner = _make_scanner({
            "utilities": [{"pair": "DTE/SO", "y": "DTE", "x": "SO"}],
            "energy": [{"pair": "XOM/CVX", "y": "XOM", "x": "CVX"}]})
        screener = _make_screener({"DTE/SO": "PROMOTE", "XOM/CVX": "PROMOTE"})
        out = quant_supervisor.recommend(
            ["utilities", "energy"], scanner=scanner, screener=screener, overview=_overview)
        assert {d["pair"] for d in out["propose_spawn"]} == {"DTE/SO", "XOM/CVX"}


class TestLiveOverviewShape:
    def test_overview_merges_zscore_into_active(self, monkeypatch):
        monkeypatch.setattr(icarus := quant_supervisor.icarus_db, "account_snapshot",
                            lambda: {"total_equity": 1.0, "available_funds": 1.0,
                                     "open_positions": 1, "as_of": "t"})
        monkeypatch.setattr(icarus, "active_pairs",
                            lambda: [{"pair": "XOM/CVX", "y": "XOM", "x": "CVX", "pair_id": 2}])
        monkeypatch.setattr(icarus, "live_pair_state",
                            lambda: [{"pair": "XOM/CVX", "z_score": 0.28, "as_of": "t"}])
        monkeypatch.setattr(icarus, "performance_summary", lambda: {"closed_trades": 0})
        ov = quant_supervisor.live_overview()
        assert ov["active_pairs"][0]["z_score"] == 0.28      # z merged into the held pair

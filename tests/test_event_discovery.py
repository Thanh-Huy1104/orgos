"""Tests for event-driven discovery (offline — fetcher/scanner/screener injected)."""

import pytest

from orgos import event_discovery as ed


def _sector_map():
    return {t: s for s, ts in _universes().items() for t in ts}


def _universes():
    return {
        "utilities": ["DUK", "SO", "DTE", "AEP"],
        "banks": ["JPM", "BAC", "WFC"],
    }


def _filings(*forms):
    return [{"form": f, "date": "2026-06-01", "primary_doc": "", "accession": ""}
            for f in forms]


def _cand(pair, y, x):
    return {"pair": pair, "y": y, "x": x, "adf_p": 0.003, "half_life": 13.0,
            "hurst": 0.27, "stable": True, "beta": 0.9, "beta_drift": 1.5,
            "factor_r2": 0.05, "sub_pvalues": [0.04, 0.02, 0.004], "sector": "utilities"}


def _dossier(pair, verdict):
    return {"pair": pair, "verdict": verdict, "structural_risk": "LOW",
            "reasons": [], "stats": {}, "leg_filings": {}}


class TestTickerSector:
    def test_known_ticker_maps_to_sector(self):
        sm = _sector_map()
        assert ed.ticker_sector("DUK", sm) == "utilities"
        assert ed.ticker_sector("jpm", sm) == "banks"

    def test_unknown_ticker_is_none(self):
        assert ed.ticker_sector("ZZZZ", _sector_map()) is None


class TestDetectEvents:
    def test_material_filing_becomes_event(self):
        def fetch(ticker):
            return _filings("8-K") if ticker == "DUK" else _filings("10-Q")

        events = ed.detect_events(universes=_universes(), fetcher=fetch)
        assert len(events) == 1
        assert events[0]["ticker"] == "DUK"
        assert events[0]["sector"] == "utilities"
        assert events[0]["risk"] == "MEDIUM"

    def test_high_risk_sorts_first(self):
        def fetch(ticker):
            if ticker == "DUK":
                return _filings("8-K")
            if ticker == "SO":
                return _filings("425")
            return _filings("10-Q")

        events = ed.detect_events(universes=_universes(), fetcher=fetch)
        assert events[0]["ticker"] == "SO" and events[0]["risk"] == "HIGH"

    def test_no_material_filings_no_events(self):
        events = ed.detect_events(universes=_universes(),
                                  fetcher=lambda t: _filings("10-Q", "4"))
        assert events == []

    def test_no_universes_no_events(self):
        events = ed.detect_events(universes=None, fetcher=lambda t: _filings("8-K"))
        assert events == []


class TestDiscoverFromEvents:
    def test_event_triggers_scan_and_gate(self):
        def fetch(ticker):
            return _filings("8-K") if ticker == "DUK" else _filings("10-Q")

        def scanner(universe, **kw):
            assert universe == "utilities"
            return {"candidates": [_cand("DTE/SO", "DTE", "SO")]}

        def screener(cands, **kw):
            return {"promote": [_dossier("DTE/SO", "PROMOTE")], "review": [], "hold": []}

        out = ed.discover_from_events(fetcher=fetch, scanner=scanner, screener=screener,
                                      universes=_universes())
        assert out["triggered_sectors"] == ["utilities"]
        assert len(out["results"]) == 1
        assert len(out["results"][0]["promote"]) == 1
        assert "1 to promote" in out["summary"]

    def test_sectors_deduped(self):
        def fetch(ticker):
            return _filings("8-K") if ticker in ("DUK", "SO") else _filings("10-Q")

        calls = []

        def scanner(universe, **kw):
            calls.append(universe)
            return {"candidates": []}

        out = ed.discover_from_events(fetcher=fetch, scanner=scanner,
                                      screener=lambda c, **k: {"promote": [], "review": [], "hold": []},
                                      universes=_universes())
        assert calls.count("utilities") == 1
        assert out["triggered_sectors"] == ["utilities"]

    def test_no_events_no_scan(self):
        calls = []

        def scanner(universe, **kw):
            calls.append(universe)
            return {"candidates": []}

        out = ed.discover_from_events(
            fetcher=lambda t: _filings("10-Q"), scanner=scanner,
            screener=lambda c, **k: {"promote": [], "review": [], "hold": []},
            universes=_universes())
        assert calls == []
        assert out["triggered_sectors"] == []
        assert "0 sector(s)" in out["summary"]

    def test_empty_scan_recorded_not_crashed(self):
        def fetch(ticker):
            return _filings("8-K") if ticker == "DUK" else _filings("10-Q")

        out = ed.discover_from_events(
            fetcher=fetch, scanner=lambda u, **k: {"candidates": []},
            screener=lambda c, **k: {"promote": [], "review": [], "hold": []},
            universes=_universes())
        assert out["results"][0]["candidates_found"] == 0

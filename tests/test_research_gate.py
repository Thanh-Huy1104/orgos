"""Tests for the research gate + SEC EDGAR risk classification (offline)."""

import pytest

from orgos.quant.sec_edgar import assess_filings
from orgos.quant.research_gate import screen_candidates, screen_pair


def _filings(*forms):
    return [{"form": f, "date": "2026-06-01", "primary_doc": "", "accession": ""}
            for f in forms]


def _pair(y="AAA", x="BBB"):
    return {"pair": f"{y}/{x}", "y": y, "x": x, "adf_p": 0.003, "half_life": 13.0,
            "hurst": 0.27, "stable": True, "beta": 0.9, "beta_drift": 1.5,
            "factor_r2": 0.05, "sub_pvalues": [0.04, 0.02, 0.004], "sector": "utilities"}


class TestAssessFilings:
    def test_merger_form_is_high(self):
        assert assess_filings(_filings("10-Q", "425"))["risk"] == "HIGH"

    def test_activist_stake_is_high(self):
        assert assess_filings(_filings("SC 13D"))["risk"] == "HIGH"

    def test_delisting_is_high(self):
        assert assess_filings(_filings("25-NSE"))["risk"] == "HIGH"

    def test_8k_is_medium(self):
        out = assess_filings(_filings("8-K", "4", "144"))
        assert out["risk"] == "MEDIUM" and out["medium_forms"] == ["8-K"]

    def test_routine_only_is_low(self):
        assert assess_filings(_filings("10-K", "10-Q", "4", "424B5"))["risk"] == "LOW"

    def test_empty_is_low(self):
        assert assess_filings([])["risk"] == "LOW"


class TestScreenPair:
    def test_clean_pair_promotes(self):
        d = screen_pair(_pair(), fetcher=lambda t: _filings("10-Q", "4"))
        assert d["verdict"] == "PROMOTE"
        assert d["structural_risk"] == "LOW"

    def test_merger_on_one_leg_holds(self):
        def fetch(t):
            return _filings("425") if t == "AAA" else _filings("10-Q")
        d = screen_pair(_pair(), fetcher=fetch)
        assert d["verdict"] == "HOLD"
        assert d["structural_risk"] == "HIGH"
        assert any("AAA" in r for r in d["reasons"])

    def test_8k_triggers_review(self):
        d = screen_pair(_pair(), fetcher=lambda t: _filings("8-K", "10-Q"))
        assert d["verdict"] == "REVIEW"
        assert d["structural_risk"] == "MEDIUM"

    def test_worst_leg_governs(self):
        # One leg clean, the other HIGH ⇒ pair is HOLD (worst-leg governs).
        def fetch(t):
            return _filings("10-Q") if t == "AAA" else _filings("SC 13D")
        assert screen_pair(_pair(), fetcher=fetch)["verdict"] == "HOLD"

    def test_stats_carried_through(self):
        d = screen_pair(_pair(), fetcher=lambda t: _filings("10-Q"))
        assert d["stats"]["half_life"] == 13.0
        assert d["stats"]["sector"] == "utilities"


class TestScreenCandidates:
    def test_groups_by_verdict(self):
        cands = [_pair("AAA", "BBB"), _pair("CCC", "DDD")]

        def fetch(t):
            return _filings("425") if t == "CCC" else _filings("10-Q")

        out = screen_candidates(cands, fetcher=fetch)
        assert out["screened"] == 2
        assert len(out["promote"]) == 1   # AAA/BBB clean
        assert len(out["hold"]) == 1      # CCC/DDD has a merger on CCC
        assert "1 to promote" in out["recommendation"]

    def test_empty_candidate_list(self):
        out = screen_candidates([], fetcher=lambda t: [])
        assert out["screened"] == 0
        assert out["promote"] == []

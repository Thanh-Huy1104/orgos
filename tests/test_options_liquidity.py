"""Tests for the options liquidity + spot-sanity validator and its rubric gate.

Two layers:
  - run_liquidity_check / _check_leg: pure logic over a mocked chain + price feed.
  - grade_options_edge Gate 4: fails an otherwise-passing run when the recommended
    structure is illiquid or built on a stale spot.
"""

import json

import pandas as pd

from orgos.tools.options_tools import _check_leg, run_liquidity_check
import orgos.options.grading as grading
from orgos.options.grading import grade_options_edge
from orgos.spawn import HandoffEnvelope, SpawnResult


# ── Fixtures / helpers ────────────────────────────────────────────────────────

def _df(rows):
    """rows: list of (strike, bid, ask, oi, vol) → normalized chain frame."""
    return pd.DataFrame(
        [{"strike": s, "bid": b, "ask": a, "open_interest": oi, "volume": v}
         for (s, b, a, oi, v) in rows]
    )


class _FakeChain:
    def __init__(self, spot, calls, puts, source="yfinance"):
        self.spot = spot
        self._calls = calls
        self._puts = puts
        self.source = source

    def for_expiry(self, expiry):
        return self._calls, self._puts


def _patch_chain(monkeypatch, chain, close=None):
    import orgos.options.chain as chain_mod
    import orgos.quant.marketdata as md
    monkeypatch.setattr(chain_mod, "get_chain", lambda *a, **k: chain)
    if close is None:
        monkeypatch.setattr(md, "get_prices",
                            lambda *a, **k: (_ for _ in ()).throw(md.MarketDataError("none")))
    else:
        monkeypatch.setattr(md, "get_prices", lambda *a, **k: pd.Series([close]))


# ── _check_leg ────────────────────────────────────────────────────────────────

class TestCheckLeg:
    def test_liquid_leg_passes(self):
        df = _df([(900, 2.0, 2.2, 500, 120)])
        leg = _check_leg(df, 900, "put", spot=120.0)
        assert leg["tradeable"]
        assert leg["reasons"] == []
        assert leg["mid"] == 2.1

    def test_zero_bid_fails(self):
        df = _df([(900, 0.0, 2.2, 500, 120)])
        leg = _check_leg(df, 900, "put", spot=120.0)
        assert not leg["tradeable"]
        assert any("two-sided" in r for r in leg["reasons"])

    def test_thin_open_interest_fails(self):
        df = _df([(900, 2.0, 2.2, 5, 0)])
        leg = _check_leg(df, 900, "put", spot=120.0)
        assert not leg["tradeable"]
        assert any("open interest" in r for r in leg["reasons"])

    def test_wide_spread_fails(self):
        df = _df([(900, 1.0, 3.0, 500, 50)])  # mid 2.0, spread 2.0 → 100%
        leg = _check_leg(df, 900, "put", spot=120.0)
        assert not leg["tradeable"]
        assert any("spread" in r for r in leg["reasons"])

    def test_no_contracts_fails(self):
        leg = _check_leg(_df([]), 900, "put", spot=120.0)
        assert not leg["tradeable"]


# ── run_liquidity_check ───────────────────────────────────────────────────────

class TestRunLiquidityCheck:
    def test_liquid_and_sane(self, monkeypatch):
        calls = _df([(130, 1.5, 1.7, 800, 40)])
        puts = _df([(110, 1.2, 1.4, 700, 30)])
        _patch_chain(monkeypatch, _FakeChain(120.0, calls, puts), close=119.0)
        out = run_liquidity_check("MU", "2026-06-26", put_strikes=[110], call_strikes=[130])
        assert out["liquid"] is True
        assert out["spot_sanity_ok"] is True
        assert len(out["legs"]) == 2

    def test_stale_spot_flagged(self, monkeypatch):
        # chain says 1190 but the feed's close is ~120 → divergence ≫ 20%
        calls = _df([(1400, 1.5, 1.7, 800, 40)])
        puts = _df([(900, 1.2, 1.4, 700, 30)])
        _patch_chain(monkeypatch, _FakeChain(1190.0, calls, puts), close=120.0)
        out = run_liquidity_check("MU", "2026-06-26", put_strikes=[900], call_strikes=[1400])
        assert out["spot_sanity_ok"] is False
        assert out["liquid"] is False
        assert any("diverges" in r for r in out["reasons"])

    def test_illiquid_leg_makes_not_liquid(self, monkeypatch):
        calls = _df([(130, 1.5, 1.7, 800, 40)])
        puts = _df([(110, 0.0, 1.4, 2, 0)])  # no bid + thin OI
        _patch_chain(monkeypatch, _FakeChain(120.0, calls, puts), close=120.0)
        out = run_liquidity_check("MU", "2026-06-26", put_strikes=[110], call_strikes=[130])
        assert out["spot_sanity_ok"] is True
        assert out["liquid"] is False
        assert out["reasons"]

    def test_no_spot_fails_sanity(self, monkeypatch):
        calls = _df([(130, 1.5, 1.7, 800, 40)])
        _patch_chain(monkeypatch, _FakeChain(None, calls, _df([])), close=120.0)
        out = run_liquidity_check("MU", "2026-06-26", call_strikes=[130])
        assert out["spot_sanity_ok"] is False


# ── Grader Gate 4 ─────────────────────────────────────────────────────────────

# An output blob that clears gates 1-3 (edge signal, tradeable IV rank, defined-risk).
_EDGE = ('{"iv_rank": 100, "signal": "sell_premium", '
         '"top_suggestion": "iron_condor", "atm_iv_pct": 80.0}')


def _result(run_id="run-liq"):
    return SpawnResult(
        envelope=HandoffEnvelope(role="options-synth", status="completed", summary="s"),
        run_id=run_id, token_usage=None, raw_output=None, tasks_output=[],
    )


def _trail(*calls):
    """calls: list of (tool, preview) tuples."""
    return [{"tool": t, "ok": True, "output_preview": p} for (t, p) in calls]


class TestLiquidityGate:
    def test_passes_and_scores_higher_when_liquid(self, monkeypatch):
        trail = _trail(
            ("scan_options_surface", _EDGE),
            ("check_options_liquidity", '{"liquid": true, "spot_sanity_ok": true}'),
        )
        monkeypatch.setattr(grading, "read_trail", lambda rid: trail)
        g = grade_options_edge(_result())
        assert g.passed
        assert "liquidity=verified" in g.notes

    def test_fails_on_stale_spot(self, monkeypatch):
        trail = _trail(
            ("scan_options_surface", _EDGE),
            ("check_options_liquidity", '{"liquid": false, "spot_sanity_ok": false}'),
        )
        monkeypatch.setattr(grading, "read_trail", lambda rid: trail)
        g = grade_options_edge(_result())
        assert not g.passed
        assert "spot-sanity" in g.failures[0]

    def test_fails_on_illiquid_legs(self, monkeypatch):
        trail = _trail(
            ("scan_options_surface", _EDGE),
            ("check_options_liquidity", '{"liquid": false, "spot_sanity_ok": true}'),
        )
        monkeypatch.setattr(grading, "read_trail", lambda rid: trail)
        g = grade_options_edge(_result())
        assert not g.passed
        assert "liquidity check FAILED" in g.failures[0]

    def test_passes_but_flags_unchecked_when_no_liquidity_call(self, monkeypatch):
        trail = _trail(("scan_options_surface", _EDGE))
        monkeypatch.setattr(grading, "read_trail", lambda rid: trail)
        g = grade_options_edge(_result())
        assert g.passed
        assert "UNCHECKED" in g.notes

    # ── Integration: real tool JSON ↔ grader contract ─────────────────────────
    # The hand-written blobs above could drift from what the tool actually emits.
    # These feed the *real* run_liquidity_check output into the grader so the
    # tool's serialized keys and the grader's regexes are tested together.

    def test_real_liquid_output_passes_grader(self, monkeypatch):
        calls = _df([(130, 1.5, 1.7, 800, 40)])
        puts = _df([(110, 1.2, 1.4, 700, 30)])
        _patch_chain(monkeypatch, _FakeChain(120.0, calls, puts), close=120.0)
        liq_json = json.dumps(run_liquidity_check(
            "MU", "2026-06-26", put_strikes=[110], call_strikes=[130]))

        trail = _trail(("scan_options_surface", _EDGE), ("check_options_liquidity", liq_json))
        monkeypatch.setattr(grading, "read_trail", lambda rid: trail)
        g = grade_options_edge(_result())
        assert g.passed
        assert "liquidity=verified" in g.notes

    def test_real_stale_spot_output_fails_grader(self, monkeypatch):
        # chain spot 1190 vs close 120 — the MU bug, end to end
        calls = _df([(1400, 1.5, 1.7, 800, 40)])
        puts = _df([(900, 1.2, 1.4, 700, 30)])
        _patch_chain(monkeypatch, _FakeChain(1190.0, calls, puts), close=120.0)
        liq_json = json.dumps(run_liquidity_check(
            "MU", "2026-06-26", put_strikes=[900], call_strikes=[1400]))

        trail = _trail(("scan_options_surface", _EDGE), ("check_options_liquidity", liq_json))
        monkeypatch.setattr(grading, "read_trail", lambda rid: trail)
        g = grade_options_edge(_result())
        assert not g.passed
        assert "spot-sanity" in g.failures[0]

    def test_no_recommendation_sentinel_is_clear_not_naked(self, monkeypatch):
        # engine declined: edge signal present but top_suggestion 'none' → clear no-edge,
        # not the misleading "'none' is not defined-risk" message.
        blob = ('{"iv_rank": 30, "signal": "buy_options", "top_suggestion": "none"}')
        trail = _trail(("scan_options_surface", blob))
        monkeypatch.setattr(grading, "read_trail", lambda rid: trail)
        g = grade_options_edge(_result())
        assert not g.passed
        assert "no recommendation" in g.failures[0]
        assert "not defined-risk" not in g.failures[0]

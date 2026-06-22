"""Options strategies — pure math tests (no network, no crewai)."""

import math

from orgos.options.strategies import (
    covered_call,
    cash_secured_put,
    bull_call_spread,
    bear_put_spread,
    iron_condor,
    long_straddle,
    suggest_strategy,
)


# ── Shared params ──────────────────────────────────────────────────────────────

S = 100.0
T = 30 / 365
r = 0.05
sigma = 0.25

# Realistic premiums from BS for the tests
from orgos.options.pricer import bs_price as _bp

CALL_100 = round(_bp(S, 100, T, r, sigma, "call"), 2)
CALL_105 = round(_bp(S, 105, T, r, sigma, "call"), 2)
CALL_110 = round(_bp(S, 110, T, r, sigma, "call"), 2)
PUT_95   = round(_bp(S, 95,  T, r, sigma, "put"),  2)
PUT_90   = round(_bp(S, 90,  T, r, sigma, "put"),  2)
PUT_100  = round(_bp(S, 100, T, r, sigma, "put"),  2)


# ── Covered call ──────────────────────────────────────────────────────────────

class TestCoveredCall:
    def _build(self):
        return covered_call(S, 105, CALL_105, T=T, r=r, sigma=sigma)

    def test_keys_present(self):
        r_ = self._build()
        for k in ("strategy", "legs", "max_profit", "breakeven", "payoff", "rationale"):
            assert k in r_

    def test_strategy_name(self):
        assert self._build()["strategy"] == "covered_call"

    def test_max_profit_above_zero(self):
        assert self._build()["max_profit"] > 0

    def test_breakeven_below_spot(self):
        r_ = self._build()
        assert r_["breakeven"] < S

    def test_payoff_list_nonempty(self):
        assert len(self._build()["payoff"]) == 80

    def test_payoff_capped_above_short_strike(self):
        r_ = self._build()
        high_pnl = [p["pnl"] for p in r_["payoff"] if p["spot"] > 110]
        if high_pnl:
            max_pnl = r_["max_profit"]
            assert all(abs(p - max_pnl) < 0.5 for p in high_pnl)


# ── Cash-secured put ──────────────────────────────────────────────────────────

class TestCashSecuredPut:
    def _build(self):
        return cash_secured_put(S, 95, PUT_95, T=T, r=r, sigma=sigma)

    def test_strategy_name(self):
        assert self._build()["strategy"] == "cash_secured_put"

    def test_max_profit_is_premium(self):
        r_ = self._build()
        assert abs(r_["max_profit"] - PUT_95) < 0.01

    def test_effective_buy_price_below_spot(self):
        assert self._build()["effective_buy_price"] < S

    def test_max_loss_positive(self):
        assert self._build()["max_loss"] > 0

    def test_payoff_flat_above_put_strike(self):
        r_ = self._build()
        flat = [p["pnl"] for p in r_["payoff"] if p["spot"] > 96]
        assert all(abs(p - r_["max_profit"]) < 0.1 for p in flat)


# ── Bull call spread ──────────────────────────────────────────────────────────

class TestBullCallSpread:
    def _build(self):
        return bull_call_spread(
            S, long_strike=100, short_strike=105,
            long_premium=CALL_100, short_premium=CALL_105,
            T=T, r=r, sigma_long=sigma, sigma_short=sigma,
        )

    def test_strategy_name(self):
        assert self._build()["strategy"] == "bull_call_spread"

    def test_net_debit_positive(self):
        assert self._build()["net_debit"] > 0

    def test_max_loss_equals_debit(self):
        r_ = self._build()
        assert abs(r_["max_loss"] - r_["net_debit"]) < 0.01

    def test_max_profit_above_zero(self):
        assert self._build()["max_profit"] > 0

    def test_max_profit_less_than_spread_width(self):
        r_ = self._build()
        assert r_["max_profit"] < (105 - 100)

    def test_breakeven_between_strikes(self):
        r_ = self._build()
        assert 100 < r_["breakeven"] < 105

    def test_greeks_positive_delta(self):
        # Bull spread should be net long delta (benefits from upside)
        assert self._build()["greeks"]["delta"] > 0

    def test_payoff_capped_above_short_strike(self):
        r_ = self._build()
        high = [p["pnl"] for p in r_["payoff"] if p["spot"] > 107]
        if high:
            assert all(abs(p - r_["max_profit"]) < 0.2 for p in high)


# ── Bear put spread ───────────────────────────────────────────────────────────

class TestBearPutSpread:
    def _build(self):
        return bear_put_spread(
            S, long_strike=100, short_strike=95,
            long_premium=PUT_100, short_premium=PUT_95,
            T=T, r=r, sigma_long=sigma, sigma_short=sigma,
        )

    def test_strategy_name(self):
        assert self._build()["strategy"] == "bear_put_spread"

    def test_net_debit_positive(self):
        assert self._build()["net_debit"] > 0

    def test_max_profit_above_zero(self):
        assert self._build()["max_profit"] > 0

    def test_breakeven_between_strikes(self):
        r_ = self._build()
        assert 95 < r_["breakeven"] < 100

    def test_greeks_negative_delta(self):
        # Bear put spread should be net short delta (benefits from downside)
        assert self._build()["greeks"]["delta"] < 0

    def test_payoff_capped_below_short_strike(self):
        r_ = self._build()
        low = [p["pnl"] for p in r_["payoff"] if p["spot"] < 93]
        if low:
            assert all(abs(p - r_["max_profit"]) < 0.2 for p in low)


# ── Iron condor ───────────────────────────────────────────────────────────────

class TestIronCondor:
    def _build(self):
        return iron_condor(
            S,
            put_short_strike=95, put_long_strike=90,
            call_short_strike=105, call_long_strike=110,
            put_short_premium=PUT_95, put_long_premium=PUT_90,
            call_short_premium=CALL_105, call_long_premium=CALL_110,
            T=T, r=r, sigma=sigma,
        )

    def test_strategy_name(self):
        assert self._build()["strategy"] == "iron_condor"

    def test_net_credit_positive(self):
        assert self._build()["net_credit"] > 0

    def test_max_profit_equals_credit(self):
        r_ = self._build()
        assert abs(r_["max_profit"] - r_["net_credit"]) < 0.01

    def test_max_loss_positive(self):
        assert self._build()["max_loss"] > 0

    def test_two_breakevens(self):
        assert len(self._build()["breakevens"]) == 2

    def test_breakevens_straddle_short_strikes(self):
        r_ = self._build()
        lo, hi = r_["breakevens"]
        assert lo < 95 and hi > 105

    def test_payoff_positive_in_profit_zone(self):
        r_ = self._build()
        mid = [p["pnl"] for p in r_["payoff"] if 96 < p["spot"] < 104]
        assert all(p > 0 for p in mid), "condor should profit between short strikes"


# ── Long straddle ─────────────────────────────────────────────────────────────

class TestLongStraddle:
    def _build(self):
        return long_straddle(S, 100, CALL_100, PUT_100, T=T, r=r, sigma=sigma)

    def test_strategy_name(self):
        assert self._build()["strategy"] == "long_straddle"

    def test_max_loss_equals_total_premium(self):
        r_ = self._build()
        assert abs(r_["max_loss"] - r_["total_premium_paid"]) < 0.01

    def test_max_profit_is_none(self):
        assert self._build()["max_profit"] is None

    def test_two_breakevens(self):
        r_ = self._build()
        assert len(r_["breakevens"]) == 2
        lo, hi = r_["breakevens"]
        assert lo < 100 < hi

    def test_near_zero_delta(self):
        # ATM straddle: call delta ≈ +0.5, put delta ≈ -0.5 → net ≈ 0
        g = self._build()["greeks"]
        assert abs(g["delta"]) < 0.15

    def test_positive_vega(self):
        # Long straddle loves volatility spikes
        assert self._build()["greeks"]["vega"] > 0

    def test_payoff_profits_on_big_move(self):
        r_ = self._build()
        far_up = [p["pnl"] for p in r_["payoff"] if p["spot"] > 115]
        far_down = [p["pnl"] for p in r_["payoff"] if p["spot"] < 85]
        assert all(p > 0 for p in far_up)
        assert all(p > 0 for p in far_down)


# ── Strategy selector ─────────────────────────────────────────────────────────

class TestSuggestStrategy:
    def test_high_iv_neutral_suggests_condor(self):
        r_ = suggest_strategy(iv_rank=70, rv=0.15, atm_iv=0.25, view="neutral")
        assert r_["top_suggestion"] == "iron_condor"

    def test_low_iv_volatile_suggests_straddle(self):
        r_ = suggest_strategy(iv_rank=15, rv=0.30, atm_iv=0.18, view="volatile")
        assert r_["top_suggestion"] == "long_straddle"

    def test_bullish_high_iv_suggests_income(self):
        r_ = suggest_strategy(iv_rank=65, rv=0.18, atm_iv=0.28, view="bullish")
        assert r_["top_suggestion"] in ("iron_condor", "covered_call", "cash_secured_put")

    def test_returns_required_keys(self):
        r_ = suggest_strategy(iv_rank=50, rv=0.20, atm_iv=0.22, view="neutral")
        for k in ("iv_rank", "atm_iv_pct", "realized_vol_pct", "vol_premium_pts",
                  "top_suggestion", "candidates"):
            assert k in r_

    def test_candidates_are_ranked(self):
        r_ = suggest_strategy(iv_rank=80, rv=0.15, atm_iv=0.30, view="neutral")
        priorities = [c["priority"] for c in r_["candidates"]]
        assert priorities == sorted(priorities)

    def test_no_edge_returns_none(self):
        r_ = suggest_strategy(iv_rank=40, rv=0.20, atm_iv=0.21, view="neutral")
        # Should still return a suggestion (even if it's "none")
        assert r_["top_suggestion"] is not None

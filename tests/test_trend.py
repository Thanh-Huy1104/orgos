"""Trend / time-series momentum backtest — pure, no network."""

import numpy as np
import pandas as pd

from orgos.quant.trend import backtest, buy_and_hold, ma_signal, portfolio, tsmom_signal


def _uptrend(n=400, drift=0.002, seed=0):
    rng = np.random.default_rng(seed)
    r = drift + rng.normal(0, 0.01, n)
    return pd.Series(100 * np.cumprod(1 + r), index=pd.RangeIndex(n))


class TestSignals:
    def test_tsmom_long_in_uptrend(self):
        p = _uptrend()
        sig = tsmom_signal(p, 60)
        assert sig.iloc[200:].mean() > 0.8  # mostly long in a steady uptrend

    def test_no_lookahead(self):
        # signal at t must not depend on price at t (it's shifted)
        p = _uptrend()
        sig = ma_signal(p, 50)
        assert sig.index.equals(p.index)
        assert sig.iloc[0] == 0.0  # nothing known on day 0


class TestBacktest:
    def test_profile_keys_and_drawdown_sign(self):
        p = _uptrend()
        m = backtest(p, tsmom_signal(p, 60), cost_bps=5.0)
        for k in ("cagr", "vol", "sharpe", "max_dd", "time_underwater", "final_mult"):
            assert k in m
        assert m["max_dd"] <= 0  # drawdown is non-positive
        assert 0 <= m["time_underwater"] <= 100

    def test_trend_beats_buyhold_on_drawdown_in_a_crash(self):
        # up then crash: trend should exit and avoid the worst of the drop
        up = _uptrend(250, drift=0.003, seed=1)
        crash = pd.Series(up.iloc[-1] * np.cumprod(1 + np.full(150, -0.01)),
                          index=pd.RangeIndex(250, 400))
        p = pd.concat([up, crash])
        trend = backtest(p, ma_signal(p, 50), cost_bps=5.0)
        hold = buy_and_hold(p)
        assert trend["max_dd"] > hold["max_dd"]  # less negative = shallower drawdown

    def test_costs_drag_returns(self):
        p = _uptrend()
        cheap = backtest(p, ma_signal(p, 20), cost_bps=0.0)
        pricey = backtest(p, ma_signal(p, 20), cost_bps=100.0)
        assert pricey["cagr"] < cheap["cagr"]


def test_portfolio_averages_streams():
    a = pd.Series(np.full(300, 0.001), index=pd.RangeIndex(300))
    b = pd.Series(np.full(300, 0.003), index=pd.RangeIndex(300))
    m = portfolio({"A": a, "B": b})
    assert m["n"] == 300 and m["cagr"] > 0

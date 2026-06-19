"""Out-of-sample pairs backtest — the money metric."""

import numpy as np
import pandas as pd

from orgos.quant.backtest import backtest_pair, walk_forward


def _mean_reverting_pair(n=400, phi=0.8, seed=0):
    """x = random-walk price; y = x with a fast mean-reverting (OU) log-spread."""
    rng = np.random.default_rng(seed)
    lx = np.log(100) + np.cumsum(rng.normal(0, 0.01, n))
    ou = np.zeros(n)
    for t in range(1, n):
        ou[t] = phi * ou[t - 1] + rng.normal(0, 0.03)
    ly = lx + ou
    idx = pd.RangeIndex(n)
    return pd.Series(np.exp(ly), index=idx), pd.Series(np.exp(lx), index=idx)


class TestBacktest:
    def test_mean_reverting_pair_trades_and_scores(self):
        y, x = _mean_reverting_pair()
        bt = backtest_pair(y, x, z_window=30, cost_bps=1.0)
        assert bt["n_trades"] > 0
        assert bt["oos_sharpe"] is not None
        assert bt["test_days"] > 0
        assert bt["win_rate"] is not None
        # a fast-reverting spread with tiny costs should be net profitable OOS
        assert bt["oos_sharpe"] > 0

    def test_insufficient_data_returns_empty(self):
        y = pd.Series(np.exp(np.linspace(0, 0.1, 50)))
        x = pd.Series(np.exp(np.linspace(0, 0.1, 50)))
        bt = backtest_pair(y, x)
        assert bt["oos_sharpe"] is None
        assert bt["n_trades"] == 0
        assert "insufficient" in bt.get("note", "")

    def test_costs_reduce_pnl(self):
        y, x = _mean_reverting_pair()
        cheap = backtest_pair(y, x, z_window=30, cost_bps=1.0)
        pricey = backtest_pair(y, x, z_window=30, cost_bps=50.0)
        # same trades, more cost → strictly lower net return
        assert pricey["oos_return"] < cheap["oos_return"]


class TestWalkForward:
    def test_multi_fold_aggregates_trades_and_folds(self):
        y, x = _mean_reverting_pair(n=800)
        wf = walk_forward(y, x, n_folds=4, z_window=30, cost_bps=1.0)
        assert wf["n_folds"] == 4
        assert wf["n_trades"] > 0
        assert 0 <= wf["folds_profitable"] <= 4
        # a fast-reverting spread should trade more often than a single split
        single = backtest_pair(y, x, z_window=30, cost_bps=1.0)
        assert wf["n_trades"] >= single["n_trades"]

    def test_short_series_falls_back_to_single_split(self):
        y, x = _mean_reverting_pair(n=150)
        wf = walk_forward(y, x, z_window=30)
        assert wf["n_folds"] in (0, 1)  # single-split fallback (or no-trade empty)

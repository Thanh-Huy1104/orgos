"""Tests for the options short-premium (VRP) backtest.

Synthetic price/VIX paths so the P&L logic is deterministic and the economic
direction is verifiable: rich IV + calm realized → profit; a crash → capped loss.
"""

import numpy as np
import pandas as pd

from orgos.quant.options_backtest import (
    _select_short_put_strike, _trade_pnl, backtest_short_premium, _summarize,
)


def _series(vals, start="2023-01-02"):
    idx = pd.bdate_range(start, periods=len(vals))
    return pd.Series(vals, index=idx, dtype=float)


# ── strike selection ──────────────────────────────────────────────────────────

class TestStrikeSelection:
    def test_target_delta_is_otm_below_spot(self):
        k = _select_short_put_strike(S=100, sigma=0.20, T=30 / 365, r=0.04,
                                     target_delta=0.30)
        assert k < 100  # a 0.30-delta put is out-of-the-money (below spot)

    def test_lower_delta_is_further_otm(self):
        k30 = _select_short_put_strike(100, 0.20, 30 / 365, 0.04, 0.30)
        k10 = _select_short_put_strike(100, 0.20, 30 / 365, 0.04, 0.10)
        assert k10 < k30  # 10-delta is further from spot than 30-delta


# ── single-trade economics ────────────────────────────────────────────────────

class TestTradePnl:
    def test_csp_keeps_full_credit_when_expires_above_strike(self):
        # spot flat at 100, put sold OTM, underlying ends at 100 → expires worthless
        t = _trade_pnl(100, 100, 0.25, structure="cash_secured_put", dte=30, r=0.04,
                       target_delta=0.30, width=5, cost_per_contract=0.65,
                       slippage_frac=0.0)
        assert t["expired_otm"]
        assert t["pnl"] > 0                     # kept the credit (minus 1 commission)

    def test_put_spread_loss_is_capped(self):
        # underlying crashes far below the long strike → max loss, not unbounded
        t = _trade_pnl(100, 50, 0.25, structure="put_spread", dte=30, r=0.04,
                       target_delta=0.30, width=5, cost_per_contract=0.65,
                       slippage_frac=0.0)
        # loss capped near −(max_loss × 100); never worse than the spread width
        assert t["pnl"] < 0
        assert t["pnl"] >= -5 * 100 - 5         # within width×100 (+ tiny cost slack)

    def test_higher_iv_collects_more_credit(self):
        lo = _trade_pnl(100, 100, 0.15, structure="put_spread", dte=30, r=0.04,
                        target_delta=0.30, width=5, cost_per_contract=0.0,
                        slippage_frac=0.0)
        hi = _trade_pnl(100, 100, 0.45, structure="put_spread", dte=30, r=0.04,
                        target_delta=0.30, width=5, cost_per_contract=0.0,
                        slippage_frac=0.0)
        assert hi["credit"] > lo["credit"]      # richer IV → fatter premium


# ── walk-forward backtest ─────────────────────────────────────────────────────

class TestBacktest:
    def test_rich_iv_calm_market_is_profitable(self):
        # 400 sessions, underlying drifts flat-ish, VIX a rich 30 the whole time:
        # implied 30% vs ~0 realized → premium selling should win on net.
        rng = np.random.default_rng(0)
        px = 100 + np.cumsum(rng.normal(0, 0.05, 400))   # nearly flat
        prices = _series(px)
        vix = _series(np.full(400, 30.0))
        r = backtest_short_premium(prices, vix, structure="put_spread", dte=30)
        assert r["n_trades"] > 5
        assert r["total_pnl"] > 0
        assert 0 <= r["win_rate"] <= 1

    def test_vix_rank_filter_reduces_trade_count(self):
        # VIX spends most of the window low and spikes only briefly; a high IV-rank
        # gate should take far fewer trades than selling unconditionally.
        rng = np.random.default_rng(1)
        px = 100 + np.cumsum(rng.normal(0, 0.1, 600))
        prices = _series(px)
        v = np.full(600, 14.0)
        v[400:430] = 35.0                      # one brief vol spike
        vix = _series(v)
        blind = backtest_short_premium(prices, vix, dte=30, min_vix_rank=0)
        timed = backtest_short_premium(prices, vix, dte=30, min_vix_rank=80,
                                       rank_window=252)
        assert timed["n_trades"] < blind["n_trades"]

    def test_insufficient_history_is_flagged(self):
        prices = _series(np.full(10, 100.0))
        vix = _series(np.full(10, 20.0))
        r = backtest_short_premium(prices, vix, dte=30)
        assert r["n_trades"] == 0 and "insufficient" in r["note"]

    def test_summary_keys_and_drawdown_sign(self):
        trades = [{"pnl": 100, "credit": 1.0, "max_loss": 4.0, "expired_otm": True},
                  {"pnl": -300, "credit": 1.0, "max_loss": 4.0, "expired_otm": False},
                  {"pnl": 80, "credit": 1.0, "max_loss": 4.0, "expired_otm": True}]
        s = _summarize(trades)
        assert s["n_trades"] == 3
        assert s["total_pnl"] == -120
        assert s["max_dd"] <= 0                  # drawdown is non-positive
        assert round(s["win_rate"], 3) == round(2 / 3, 3)

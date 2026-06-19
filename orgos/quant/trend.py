"""Trend / time-series momentum — a risk premium that *persists*.

Unlike arbitrage (find a mispricing, collect risk-free — mostly gone), trend
following gets paid to bear a risk most people won't: it rides big moves and cuts
losers, earning a positive long-run premium in exchange for whipsaw losses in chop
and giving back gains at turns. It is the most empirically robust "strategy that
works" on record, and strongest in young/under-arbed markets like crypto.

This is deliberately honest: the backtest reports the *whole* profile — CAGR and
Sharpe but also **max drawdown** and **time underwater** — because "works" means
positive over years *through* an ugly stretch you must survive, not a smooth line.

Pure functions on a price series; no network, no lookahead (signals are shifted).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

PERIODS_PER_YEAR = 365  # crypto trades every day


# ── Signals (long=1 / flat=0; shifted so day t uses only info through t-1) ─────

def tsmom_signal(prices: pd.Series, lookback: int = 90) -> pd.Series:
    """Time-series momentum: long if the trailing ``lookback``-day return > 0."""
    return (prices.pct_change(lookback) > 0).astype(float).shift(1).fillna(0.0)


def ma_signal(prices: pd.Series, window: int = 100) -> pd.Series:
    """Moving-average trend: long while price is above its ``window``-day average."""
    return (prices > prices.rolling(window).mean()).astype(float).shift(1).fillna(0.0)


# ── Backtest ──────────────────────────────────────────────────────────────────

def strategy_returns(prices: pd.Series, signal: pd.Series, *, cost_bps: float = 10.0) -> pd.Series:
    """Net daily returns of running ``signal`` on ``prices`` (after switch costs)."""
    prices = prices.dropna()
    r = prices.pct_change().fillna(0.0)
    pos = signal.reindex(prices.index).fillna(0.0)
    cost = pos.diff().abs().fillna(0.0) * (cost_bps / 1e4)
    return pos * r - cost


def backtest(prices: pd.Series, signal: pd.Series, *, cost_bps: float = 10.0,
             periods_per_year: int = PERIODS_PER_YEAR) -> dict:
    """Run a 0/1 (or -1/0/1) signal on a price series; return the honest profile."""
    return _metrics(strategy_returns(prices, signal, cost_bps=cost_bps), periods_per_year)


def buy_and_hold(prices: pd.Series, *, periods_per_year: int = PERIODS_PER_YEAR) -> dict:
    """The honest benchmark: does the strategy beat just holding the asset?"""
    prices = prices.dropna()
    return _metrics(prices.pct_change().fillna(0.0), periods_per_year)


def portfolio(returns_by_asset: dict[str, pd.Series],
              *, periods_per_year: int = PERIODS_PER_YEAR) -> dict:
    """Equal-weight a set of per-asset net-return streams over their common dates."""
    df = pd.DataFrame(returns_by_asset).dropna()
    return _metrics(df.mean(axis=1), periods_per_year)


def _metrics(net: pd.Series, periods_per_year: int) -> dict:
    net = net.dropna()
    n = len(net)
    if n < 2 or net.std() == 0:
        return {"n": int(n), "cagr": None, "vol": None, "sharpe": None,
                "max_dd": None, "time_underwater": None, "final_mult": None}
    equity = (1 + net).cumprod()
    dd = equity / equity.cummax() - 1
    return {
        "n": int(n),
        "final_mult": round(float(equity.iloc[-1]), 2),
        "cagr": round((float(equity.iloc[-1]) ** (periods_per_year / n) - 1) * 100, 1),
        "vol": round(float(net.std()) * np.sqrt(periods_per_year) * 100, 1),
        "sharpe": round(float(net.mean() / net.std() * np.sqrt(periods_per_year)), 2),
        "max_dd": round(float(dd.min()) * 100, 1),
        "time_underwater": round(float((dd < -1e-9).mean()) * 100, 1),
    }

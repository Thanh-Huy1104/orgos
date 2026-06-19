"""Out-of-sample pairs backtest — the money metric.

Cointegration p-values say "is this a real relationship." They do NOT say "would
trading it have made money." This module answers the P&L question honestly, and
— via walk-forward — across multiple regimes so the number isn't a one-window
fluke:

  1. Fit the hedge ratio on past data only (re-fit per fold).
  2. Trade the canonical z-score reversion strategy on the held-out fold (enter at
     |z| > entry, exit near 0, stop at |z| > stop). No lookahead — the z-score
     uses a trailing rolling window.
  3. Report net Sharpe / return / #trades / win-rate / max-drawdown AFTER costs,
     plus how many folds were profitable (robustness across regimes).

A 100% win rate over 4 trades in one window is noise; a positive Sharpe over many
trades across several folds is a (tentative) edge. ``n_trades`` and
``folds_profitable`` are what tell those apart — surface them.

A backtest is still history, and a far better selector than in-sample adf_p — not
a promise. Sizing/execution/risk live in Icarus, not here.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.api as sm

_EMPTY = {"oos_sharpe": None, "oos_return": None, "n_trades": 0, "win_rate": None,
          "max_dd": None, "test_days": 0, "n_folds": 0, "folds_profitable": 0}


def _logp(s: pd.Series, use_log: bool) -> np.ndarray:
    a = s.to_numpy(float)
    return np.log(a) if use_log else a


def _run_strategy(spread: pd.Series, lo: int, hi: int, *, beta: float,
                  entry_z: float, exit_z: float, stop_z: float,
                  z_window: int, cost_bps: float):
    """Trade the z-score reversion strategy over spread[lo:hi]. Returns
    (net P&L series over the window, entry count, per-trade P&L list)."""
    mu = spread.rolling(z_window, min_periods=z_window).mean()
    sd = spread.rolling(z_window, min_periods=z_window).std()
    z = (spread - mu) / sd
    dspread = spread.diff()

    positions = np.zeros(len(spread))
    pos = 0
    entries = 0
    for t in range(lo, hi):
        zt = z.iloc[t]
        if not np.isnan(zt):
            if pos == 0:
                if zt > entry_z:
                    pos, entries = -1, entries + 1
                elif zt < -entry_z:
                    pos, entries = 1, entries + 1
            elif abs(zt) < exit_z or abs(zt) > stop_z:
                pos = 0
        positions[t] = pos
    positions = pd.Series(positions, index=spread.index)

    pnl = positions.shift(1) * dspread
    cost = positions.diff().abs().fillna(0.0) * (cost_bps / 1e4) * (1 + abs(beta))
    net = (pnl - cost).fillna(0.0).iloc[lo:hi]

    trades: list[float] = []
    in_trade, acc = False, 0.0
    pos_win, net_win = positions.iloc[lo:hi].to_numpy(), net.to_numpy()
    for k in range(len(pos_win)):
        if pos_win[k] != 0 and not in_trade:
            in_trade, acc = True, 0.0
        if in_trade:
            acc += float(net_win[k])
        if pos_win[k] == 0 and in_trade:
            in_trade, _ = False, trades.append(acc)
    if in_trade:
        trades.append(acc)
    return net, entries, trades


def _metrics(net: pd.Series, entries: int, trades: list[float],
             *, n_folds: int, folds_profitable: int) -> dict:
    if entries == 0 or net.std() == 0:
        return dict(_EMPTY, test_days=int(len(net)), n_folds=n_folds, note="no trades")
    cum = net.cumsum()
    win_rate = float(np.mean([t > 0 for t in trades])) if trades else None
    return {
        "oos_sharpe": round(float(net.mean() / net.std() * np.sqrt(252)), 3),
        "oos_return": round(float(net.sum()), 4),
        "n_trades": int(entries),
        "win_rate": round(win_rate, 3) if win_rate is not None else None,
        "max_dd": round(float((cum - cum.cummax()).min()), 4),
        "test_days": int(len(net)),
        "n_folds": n_folds,
        "folds_profitable": folds_profitable,
    }


def backtest_pair(
    y: pd.Series, x: pd.Series, *, use_log: bool = True, train_frac: float = 0.5,
    entry_z: float = 2.0, exit_z: float = 0.5, stop_z: float = 4.0,
    z_window: int = 60, cost_bps: float = 10.0,
) -> dict:
    """Single train/test split backtest of one pair (one OOS window)."""
    df = pd.concat([y, x], axis=1, join="inner").dropna()
    n = len(df)
    if n < 120:
        return dict(_EMPTY, note="insufficient data")
    ys, xs = _logp(df.iloc[:, 0], use_log), _logp(df.iloc[:, 1], use_log)
    split = int(n * train_frac)
    if split < 40 or n - split < 40:
        return dict(_EMPTY, note="train/test split too small")
    alpha, beta = sm.OLS(ys[:split], sm.add_constant(xs[:split])).fit().params
    spread = pd.Series(ys - (alpha + beta * xs))
    net, entries, trades = _run_strategy(
        spread, split, n, beta=beta, entry_z=entry_z, exit_z=exit_z,
        stop_z=stop_z, z_window=z_window, cost_bps=cost_bps)
    return _metrics(net, entries, trades, n_folds=1,
                    folds_profitable=int(net.sum() > 0) if entries else 0)


def walk_forward(
    y: pd.Series, x: pd.Series, *, use_log: bool = True, n_folds: int = 4,
    entry_z: float = 2.0, exit_z: float = 0.5, stop_z: float = 4.0,
    z_window: int = 60, cost_bps: float = 10.0,
) -> dict:
    """Walk-forward backtest: re-fit the hedge ratio before each held-out fold and
    trade it, then aggregate one combined OOS track record across all folds.

    The hedge ratio for fold *f* is fit on every observation *before* that fold
    (expanding window) — no lookahead. ``folds_profitable`` says in how many of
    the ``n_folds`` regimes the pair actually made money.
    """
    df = pd.concat([y, x], axis=1, join="inner").dropna()
    n = len(df)
    if n < 200:  # too short for meaningful folds → one split
        return backtest_pair(y, x, use_log=use_log, entry_z=entry_z, exit_z=exit_z,
                             stop_z=stop_z, z_window=z_window, cost_bps=cost_bps)
    ys, xs = _logp(df.iloc[:, 0], use_log), _logp(df.iloc[:, 1], use_log)

    start = max(z_window + 40, n // (n_folds + 1))  # initial train, ≥ warmup
    block = (n - start) // n_folds
    if block < 30:
        return backtest_pair(y, x, use_log=use_log, entry_z=entry_z, exit_z=exit_z,
                             stop_z=stop_z, z_window=z_window, cost_bps=cost_bps)

    nets: list[pd.Series] = []
    all_trades: list[float] = []
    total_entries = 0
    folds_profitable = 0
    for f in range(n_folds):
        lo = start + f * block
        hi = n if f == n_folds - 1 else start + (f + 1) * block
        alpha, beta = sm.OLS(ys[:lo], sm.add_constant(xs[:lo])).fit().params  # train < fold
        spread = pd.Series(ys - (alpha + beta * xs), index=df.index)
        net, entries, trades = _run_strategy(
            spread, lo, hi, beta=beta, entry_z=entry_z, exit_z=exit_z,
            stop_z=stop_z, z_window=z_window, cost_bps=cost_bps)
        nets.append(net)
        all_trades += trades
        total_entries += entries
        folds_profitable += int(net.sum() > 0)

    combined = pd.concat(nets)
    return _metrics(combined, total_entries, all_trades,
                    n_folds=n_folds, folds_profitable=folds_profitable)

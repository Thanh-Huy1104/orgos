"""Funding-rate carry — research for the crypto basis trade (cash-and-carry).

A perpetual's funding rate is a mechanical payment between longs and shorts. When
it's positive you can hold **long spot + short perp** (delta-neutral) and *collect*
the funding regardless of price. This module is the research half of that trade:

  - ``summarize_funding`` / ``scan_funding`` — where is the carry *now*, and is it
    consistent (``pct_positive``) or spiky?
  - ``carry_backtest`` — would harvesting a coin's funding have *netted* money over
    history, through the negative-funding regimes and after costs? This is the
    honest money question; funding arb is real but regime-dependent.

Deterministic math is separated from the ccxt fetch so it's testable offline. This
desk only researches/ranks — capturing the carry needs an execution + custody layer
(a crypto venue), not Interactive Brokers, and carries exchange/liquidation risk.
"""

from __future__ import annotations

import os
from typing import Any

import numpy as np

# Binance perps fund every 8h (3×/day). Annualisation = intervals per year.
DEFAULT_INTERVAL_H = 8


def _intervals_per_year(interval_h: int = DEFAULT_INTERVAL_H) -> float:
    return (24.0 / interval_h) * 365.0


def annualize(rate_per_interval: float, interval_h: int = DEFAULT_INTERVAL_H) -> float:
    """A per-interval funding rate → simple annualised %."""
    return rate_per_interval * _intervals_per_year(interval_h) * 100.0


# ── Pure analytics (no network — unit-tested) ─────────────────────────────────

def summarize_funding(rates: list[float], *, interval_h: int = DEFAULT_INTERVAL_H) -> dict:
    """Current/average funding, annualised, and how often it was positive."""
    arr = np.asarray([r for r in rates if r is not None], float)
    if arr.size == 0:
        return {"n": 0, "now_apr": None, "avg_apr": None, "pct_positive": None}
    return {
        "n": int(arr.size),
        "now_apr": round(annualize(float(arr[-1]), interval_h), 2),
        "avg_apr": round(annualize(float(arr.mean()), interval_h), 2),
        "pct_positive": round(float((arr > 0).mean()) * 100, 1),
    }


def carry_backtest(
    rates: list[float], *, interval_h: int = DEFAULT_INTERVAL_H, cost_bps: float = 4.0,
    regime_window: int = 0, entry_threshold: float = 0.0,
) -> dict:
    """Backtest a delta-neutral funding harvester over a funding-rate history.

    Always-on (``regime_window=0``): hold the position the whole window and net the
    signed funding each interval (you *pay* when funding is negative). One round-trip
    cost. Regime-filtered (``regime_window>0``): only hold when the trailing-mean
    funding exceeds ``entry_threshold``, paying ``cost_bps`` per entry/exit — so a
    negative regime is sat out rather than bled.

    Returns net APR after costs, Sharpe of the funding stream, max drawdown (the
    worst negative-funding stretch), % of intervals positive, and time in market.
    """
    arr = np.asarray([r for r in rates if r is not None], float)
    n = arr.size
    if n < 2:
        return {"n": int(n), "net_apr": None, "gross_apr": None, "sharpe": None,
                "max_dd": None, "pct_positive": None, "time_in_market": None, "switches": 0}

    if regime_window > 0:
        held = np.zeros(n)
        for t in range(n):
            if t >= regime_window and arr[t - regime_window:t].mean() > entry_threshold:
                held[t] = 1.0
        switches = int(np.abs(np.diff(np.concatenate([[0.0], held]))).sum())
    else:
        held = np.ones(n)
        switches = 1  # one entry (and an implicit exit at the end)

    pnl = held * arr                       # funding received while held (signed)
    ipy = _intervals_per_year(interval_h)
    years = n / ipy
    cost = switches * (cost_bps / 1e4)
    net_cum = float(pnl.sum() - cost)
    cum = np.cumsum(pnl)
    max_dd = float((cum - np.maximum.accumulate(cum)).min()) if n else 0.0
    std = float(pnl.std())
    sharpe = float(pnl.mean() / std * np.sqrt(ipy)) if std > 0 else 0.0

    return {
        "n": int(n),
        "gross_apr": round(float(arr.mean()) * ipy * 100, 2),
        "net_apr": round(net_cum / years * 100, 2) if years > 0 else None,
        "sharpe": round(sharpe, 2),
        "max_dd": round(max_dd * 100, 3),           # % of notional, worst drawdown
        "pct_positive": round(float((arr > 0).mean()) * 100, 1),
        "time_in_market": round(float(held.mean()) * 100, 1),
        "switches": switches,
    }


# ── ccxt fetch (network) ──────────────────────────────────────────────────────

def _exchange():
    import ccxt
    name = os.environ.get("EXCHANGE_NAME", "binance")
    return getattr(ccxt, name)({"enableRateLimit": True})


def fetch_funding_history(coin: str, days: int = 365, *, quote: str = "USDT",
                          exchange: Any = None) -> list[float]:
    """Per-interval funding rates for a linear perp over the last ``days`` (ccxt)."""
    ex = exchange or _exchange()
    sym = f"{coin}/{quote}:{quote}"
    since = ex.milliseconds() - days * 24 * 3600 * 1000
    hist = ex.fetch_funding_rate_history(sym, since=since, limit=1000)
    return [h["fundingRate"] for h in hist if h.get("fundingRate") is not None]


def scan_funding(coins: list[str], *, days: int = 14, exchange: Any = None) -> list[dict]:
    """Rank coins by recent annualised funding (the live carry landscape)."""
    ex = exchange or _exchange()
    out: list[dict] = []
    for c in coins:
        try:
            rates = fetch_funding_history(c, days, exchange=ex)
        except Exception as exc:  # noqa: BLE001 — skip a bad symbol, keep scanning
            out.append({"coin": c, "error": f"{type(exc).__name__}: {exc}"[:60]})
            continue
        out.append({"coin": c, **summarize_funding(rates)})
    out.sort(key=lambda r: (r.get("avg_apr") is None, -(r.get("avg_apr") or -1e9)))
    return out

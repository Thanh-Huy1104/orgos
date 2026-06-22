"""Volatility monitoring — realized vol, regime detection, VIX, and IV rank.

Two layers:
  1. Realized vol — rolling historical volatility from price returns. Used to:
     - Classify market regimes (low / medium / high vol)
     - Size positions proportionally to risk (inverse-vol weighting)
     - Detect vol spikes (sudden jumps that signal inflection points)

  2. Implied vol / IV rank — what options buyers currently price in, expressed
     as a percentile vs the trailing year. High IV rank → options expensive →
     sell premium. Low IV rank → options cheap → buy protection or directional.

Pure analytics are separated from data fetching so the math is unit-testable.
"""

from __future__ import annotations

import datetime as dt
from typing import Literal

import numpy as np
import pandas as pd


# ── Realized volatility ───────────────────────────────────────────────────────

EQUITIES_PER_YEAR = 252
CRYPTO_PER_YEAR = 365


def realized_vol(
    prices: pd.Series,
    window: int = 20,
    *,
    periods_per_year: int = EQUITIES_PER_YEAR,
) -> pd.Series:
    """Rolling annualized realized volatility (close-to-close)."""
    r = prices.pct_change()
    return r.rolling(window).std() * np.sqrt(periods_per_year)


def vol_regime(
    vol: pd.Series,
    *,
    low_pct: float = 33.0,
    high_pct: float = 67.0,
) -> pd.Series:
    """Classify each day as 'low' / 'medium' / 'high' vol based on
    rolling percentile rank vs the full sample seen so far.

    Uses expanding rank so there's no lookahead.
    """
    rank = vol.expanding().rank(pct=True) * 100
    regime: pd.Series = pd.Series("medium", index=vol.index, dtype=object)
    regime[rank <= low_pct] = "low"
    regime[rank >= high_pct] = "high"
    regime[vol.isna()] = None
    return regime


def vol_position_size(
    vol: pd.Series,
    *,
    target_vol: float = 0.15,
    max_leverage: float = 1.0,
) -> pd.Series:
    """Scale a unit position down when realized vol is high.

    Returns a scalar in (0, max_leverage]: position size = target_vol / realized_vol,
    capped at max_leverage. When vol is NaN the size is 0 (stay flat).

    Example: target 15% annualised risk. If realized vol is 30%, size = 0.5 (half).
    """
    size = (target_vol / vol).clip(upper=max_leverage)
    return size.fillna(0.0)


def vol_spike(
    vol: pd.Series,
    *,
    window: int = 20,
    z_threshold: float = 2.0,
) -> pd.Series:
    """Flag days where realized vol jumped more than ``z_threshold`` standard
    deviations above its recent rolling mean.  Spike = potential inflection point.
    """
    rolling_mean = vol.rolling(window).mean()
    rolling_std = vol.rolling(window).std()
    z = (vol - rolling_mean) / rolling_std.replace(0, np.nan)
    return z >= z_threshold


# ── Vol-aware signal scaling ───────────────────────────────────────────────────

def vol_scaled_signal(
    signal: pd.Series,
    prices: pd.Series,
    *,
    vol_window: int = 20,
    target_vol: float = 0.15,
    max_leverage: float = 1.0,
    periods_per_year: int = EQUITIES_PER_YEAR,
) -> pd.Series:
    """Multiply a 0/1 trend signal by the inverse-vol position size.

    Drop-in replacement for a raw signal in trend.strategy_returns():
    when vol is high the position shrinks; when low it's closer to 1.
    This is the core of risk-parity / vol-targeting: same risk every day,
    not same notional every day.
    """
    rv = realized_vol(prices, vol_window, periods_per_year=periods_per_year)
    size = vol_position_size(rv, target_vol=target_vol, max_leverage=max_leverage)
    return (signal * size).shift(1).fillna(0.0)  # shift keeps the no-lookahead guarantee


# ── VIX (market fear gauge) ───────────────────────────────────────────────────

def fetch_vix(lookback_days: int = 252) -> pd.Series:
    """VIX daily closes via yfinance.  Returns a Series indexed by date."""
    import yfinance as yf

    end = dt.date.today()
    start = end - dt.timedelta(days=int(lookback_days * 1.6) + 14)
    df = yf.download("^VIX", start=str(start), end=str(end), progress=False, auto_adjust=True)
    if df is None or df.empty:
        return pd.Series(dtype=float, name="VIX")
    close = df["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    close = close.astype(float)
    close.name = "VIX"
    return close.tail(lookback_days)


def vix_regime(vix: pd.Series) -> pd.Series:
    """Rule-of-thumb VIX regimes (widely used market convention):
    < 15 = calm, 15–25 = normal uncertainty, 25–35 = elevated fear, > 35 = panic.
    """
    regime: pd.Series = pd.Series("normal", index=vix.index, dtype=object)
    regime[vix < 15] = "calm"
    regime[vix >= 25] = "fear"
    regime[vix >= 35] = "panic"
    regime[vix.isna()] = None
    return regime


# ── Summary dict (dashboard / agent context) ──────────────────────────────────

def vol_summary(
    prices: pd.Series,
    *,
    vol_window: int = 20,
    periods_per_year: int = EQUITIES_PER_YEAR,
    vix: pd.Series | None = None,
) -> dict:
    """Full realized-vol snapshot for one asset, ready for display or injection.

    Returns:
        current_vol: annualized realized vol as of the last bar (%)
        vol_1m_avg: 1-month average realized vol (%)
        vol_3m_avg: 3-month average realized vol (%)
        regime: 'low' / 'medium' / 'high' (percentile-based)
        spike: True if today is a vol spike
        position_size_15pct: suggested position scalar for 15% target vol
        vix_current: latest VIX level (if provided)
        vix_regime: 'calm' / 'normal' / 'fear' / 'panic' (if provided)
    """
    rv = realized_vol(prices, vol_window, periods_per_year=periods_per_year)
    regime = vol_regime(rv)
    spike = vol_spike(rv)

    current = rv.iloc[-1] if len(rv) else float("nan")
    avg_1m = rv.tail(21).mean()
    avg_3m = rv.tail(63).mean()

    result: dict = {
        "current_vol_pct": round(current * 100, 1) if not np.isnan(current) else None,
        "vol_1m_avg_pct": round(avg_1m * 100, 1) if not np.isnan(avg_1m) else None,
        "vol_3m_avg_pct": round(avg_3m * 100, 1) if not np.isnan(avg_3m) else None,
        "regime": regime.iloc[-1] if len(regime) else None,
        "spike_today": bool(spike.iloc[-1]) if len(spike) else False,
        "position_size_15pct": round(
            float(vol_position_size(rv).iloc[-1]), 3
        ) if len(rv) else None,
    }

    if vix is not None and len(vix):
        vr = vix_regime(vix)
        result["vix_current"] = round(float(vix.iloc[-1]), 1)
        result["vix_regime"] = vr.iloc[-1]

    return result


# ── IV rank (options implied volatility) ──────────────────────────────────────

def _atm_iv(ticker_obj: object, expiry: str) -> float | None:
    """Mean IV of the two nearest-the-money strikes from one expiry."""
    try:
        chain = ticker_obj.option_chain(expiry)  # type: ignore[attr-defined]
        calls = chain.calls[["strike", "impliedVolatility"]].dropna()
        spot = ticker_obj.info.get("regularMarketPrice") or ticker_obj.fast_info.get("lastPrice")  # type: ignore[attr-defined]
        if spot is None or calls.empty:
            return None
        idx = (calls["strike"] - spot).abs().nsmallest(2).index
        return float(calls.loc[idx, "impliedVolatility"].mean())
    except Exception:  # noqa: BLE001
        return None


def iv_rank(
    ticker: str,
    *,
    lookback_days: int = 252,
) -> dict:
    """IV rank for one equity ticker using yfinance options data.

    IV rank = (current IV - 52w low IV) / (52w high IV - 52w low IV) × 100.
    0 = cheapest options have been all year; 100 = most expensive.

    Interpretation:
      > 50  → IV is elevated → options sellers have the edge (sell premium)
      < 20  → IV is depressed → options buyers pay less than usual (buy protection)

    Uses the nearest expiry as a proxy for spot IV (cleanest signal).
    """
    import yfinance as yf

    tk = yf.Ticker(ticker)
    exps = getattr(tk, "options", None)
    if not exps:
        return {"ticker": ticker, "error": "no options data"}

    # Use the nearest expiry that is at least 7 days out (avoid pin risk)
    today = dt.date.today()
    valid = [
        e for e in exps
        if (dt.date.fromisoformat(e) - today).days >= 7
    ]
    if not valid:
        return {"ticker": ticker, "error": "no valid expiry (all < 7 days out)"}

    current_iv = _atm_iv(tk, valid[0])
    if current_iv is None:
        return {"ticker": ticker, "error": "could not read IV from options chain"}

    # Build a 52-week IV history by sampling ~monthly expiries to reduce API calls.
    # We collect IVs from all available expiries and treat them as a proxy history.
    sample_ivs: list[float] = []
    for exp in exps[:12]:  # cap at 12 expiries (~1 year of monthlies)
        iv = _atm_iv(tk, exp)
        if iv is not None:
            sample_ivs.append(iv)

    if len(sample_ivs) < 2:
        return {
            "ticker": ticker,
            "current_iv_pct": round(current_iv * 100, 1),
            "iv_rank": None,
            "note": "insufficient expiries for rank (< 2 samples)",
        }

    iv_low = min(sample_ivs)
    iv_high = max(sample_ivs)
    rank = 0.0 if iv_high == iv_low else (current_iv - iv_low) / (iv_high - iv_low) * 100

    signal: str
    if rank >= 50:
        signal = "sell_premium"  # options expensive vs recent range
    elif rank <= 20:
        signal = "buy_options"   # options cheap vs recent range
    else:
        signal = "neutral"

    return {
        "ticker": ticker,
        "current_iv_pct": round(current_iv * 100, 1),
        "iv_low_pct": round(iv_low * 100, 1),
        "iv_high_pct": round(iv_high * 100, 1),
        "iv_rank": round(rank, 1),
        "signal": signal,
        "samples": len(sample_ivs),
    }


def scan_iv_rank(
    tickers: list[str],
    *,
    lookback_days: int = 252,
    min_rank_for_sell: float = 50.0,
) -> list[dict]:
    """IV rank scan across a list of tickers, sorted by IV rank descending.

    High-rank entries are candidates for premium-selling options strategies.
    Low-rank entries are candidates for cheap protection or directional options.
    """
    results = []
    for t in tickers:
        row = iv_rank(t, lookback_days=lookback_days)
        results.append(row)

    sortable = [r for r in results if r.get("iv_rank") is not None]
    unsortable = [r for r in results if r.get("iv_rank") is None]
    sortable.sort(key=lambda r: r["iv_rank"], reverse=True)
    return sortable + unsortable

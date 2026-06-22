"""IV surface analytics — skew, term structure, and IV vs realized vol.

Takes a fetched OptionChain and extracts the market's volatility "surface":
how expensive options are by strike (smile/skew) and by expiry (term structure).
These are the inputs to strategy selection — the surface tells you where the
market is pricing in fear, complacency, or upcoming events.

All functions are pure (take DataFrames, return dicts/lists). No network calls.

Key concepts:
  Skew:           IV is usually higher for low strikes (put skew) than high strikes
                  (call skew) because investors pay up for crash protection. When
                  skew is steep, puts are expensive relative to calls — a sign the
                  market is nervous about downside. The 25-delta skew measures this.

  Term structure:  Near-term options are usually cheaper (lower IV) than far-dated
                  unless a specific event (earnings, FOMC) inflates near-term IV.
                  Contango = far IV > near IV (normal). Backwardation = near > far
                  (fear / event-driven).

  IV vs RV:       The key edge signal. If 30-day ATM IV is 25% but the stock has
                  realised only 15% vol over recent history, options are overpriced
                  → sell premium. If IV < RV → options cheap → buy them.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from .chain import OptionChain


# ── ATM IV ────────────────────────────────────────────────────────────────────

def atm_iv(calls: pd.DataFrame, puts: pd.DataFrame, spot: float) -> float | None:
    """Mean implied vol of the two nearest-the-money strikes from one expiry.

    Uses calls only (avoids put-call parity noise from illiquid puts). Returns
    None if the chain is empty or IV data is missing.
    """
    if calls.empty or "implied_vol" not in calls.columns:
        return None
    valid = calls[calls["implied_vol"].notna() & (calls["implied_vol"] > 0)]
    if valid.empty:
        return None
    nearest = valid.iloc[(valid["strike"] - spot).abs().argsort()[:2]]
    iv = float(nearest["implied_vol"].mean())
    return iv if iv > 0 else None


# ── Skew ──────────────────────────────────────────────────────────────────────

def _delta_strike(df: pd.DataFrame, spot: float, target_delta: float) -> float | None:
    """Find the strike whose delta is closest to ``target_delta`` (0-1 scale)."""
    if "delta" not in df.columns:
        return None
    valid = df[df["delta"].notna()]
    if valid.empty:
        return None
    idx = (valid["delta"] - target_delta).abs().idxmin()
    return float(valid.loc[idx, "implied_vol"]) if "implied_vol" in valid.columns else None


def iv_skew(
    calls: pd.DataFrame,
    puts: pd.DataFrame,
    spot: float,
) -> dict:
    """25-delta skew and risk reversal for one expiry.

    Returns:
        atm_iv:        ATM implied vol
        put_25d_iv:    IV at the 25-delta put (low strike — crash protection)
        call_25d_iv:   IV at the 25-delta call (high strike — upside)
        skew_25d:      put_25d_iv - call_25d_iv  (positive = puts expensive, typical)
        risk_reversal: call_25d_iv - put_25d_iv  (positive = calls expensive, bullish market)
        interpretation: plain-text read of the skew

    Note: 25-delta strikes require the chain to have a delta column. yfinance
    does not always provide this — we fall back to ±10% OTM strikes as a proxy.
    """
    atm = atm_iv(calls, puts, spot)

    # Try delta-based 25d strikes first, fall back to ±10% OTM proxy
    put_iv = _delta_strike(puts, spot, 0.25)
    call_iv = _delta_strike(calls, spot, 0.25)

    if put_iv is None and not puts.empty and "implied_vol" in puts.columns:
        # Proxy: strike nearest to spot * 0.90
        proxy_k = spot * 0.90
        valid = puts[puts["implied_vol"].notna() & (puts["implied_vol"] > 0)]
        if not valid.empty:
            idx = (valid["strike"] - proxy_k).abs().idxmin()
            put_iv = float(valid.loc[idx, "implied_vol"])

    if call_iv is None and not calls.empty and "implied_vol" in calls.columns:
        proxy_k = spot * 1.10
        valid = calls[calls["implied_vol"].notna() & (calls["implied_vol"] > 0)]
        if not valid.empty:
            idx = (valid["strike"] - proxy_k).abs().idxmin()
            call_iv = float(valid.loc[idx, "implied_vol"])

    skew = None
    rr = None
    if put_iv is not None and call_iv is not None:
        skew = round(put_iv - call_iv, 4)
        rr = round(call_iv - put_iv, 4)

    # Interpretation
    interp = "insufficient data"
    if atm is not None and skew is not None:
        if skew > 0.05:
            interp = "steep put skew — market paying heavily for crash protection"
        elif skew > 0.02:
            interp = "normal put skew — moderate crash protection demand"
        elif skew < -0.02:
            interp = "call skew — market pricing in upside (unusual, often pre-squeeze)"
        else:
            interp = "flat skew — balanced directional demand"

    return {
        "atm_iv": round(atm, 4) if atm is not None else None,
        "put_25d_iv": round(put_iv, 4) if put_iv is not None else None,
        "call_25d_iv": round(call_iv, 4) if call_iv is not None else None,
        "skew_25d": skew,
        "risk_reversal": rr,
        "interpretation": interp,
    }


# ── Term structure ─────────────────────────────────────────────────────────────

def term_structure(chain: "OptionChain") -> list[dict]:
    """ATM IV across all expiries — the vol term structure.

    Returns a list of dicts sorted by DTE (nearest first):
        expiry:  ISO date string
        dte:     calendar days to expiry
        atm_iv:  ATM implied vol for that expiry (None if unavailable)

    Contango (near IV < far IV) is normal — the market expects more uncertainty
    further out. Backwardation (near IV > far IV) signals a near-term event.
    """
    if chain.spot is None:
        return []

    result = []
    for expiry in chain.expiries:
        calls, puts = chain.for_expiry(expiry)
        iv = atm_iv(calls, puts, chain.spot)
        dte = calls["dte"].iloc[0] if not calls.empty and "dte" in calls.columns else None
        result.append({
            "expiry": expiry,
            "dte": dte,
            "atm_iv": round(iv, 4) if iv is not None else None,
        })

    result.sort(key=lambda r: r["dte"] if r["dte"] is not None else 9999)

    # Classify shape
    valid = [r for r in result if r["atm_iv"] is not None]
    if len(valid) >= 2:
        shape = "contango" if valid[-1]["atm_iv"] > valid[0]["atm_iv"] else "backwardation"
        for r in result:
            r["structure"] = shape
    return result


# ── IV vs Realized vol ─────────────────────────────────────────────────────────

def iv_vs_rv(
    atm_implied_vol: float,
    realized_vol: float,
    *,
    dte: int = 30,
) -> dict:
    """Compare implied volatility to realized volatility to identify edge.

    Args:
        atm_implied_vol: Current ATM IV for a specific expiry (annualized, e.g. 0.25)
        realized_vol:    Historical realized vol over a comparable window (annualized)
        dte:             Days to expiry (context for interpretation)

    Returns:
        iv:              Implied vol (annualized %)
        rv:              Realized vol (annualized %)
        vol_premium:     IV - RV  (positive = options overpriced vs history)
        vol_premium_pct: Premium as % of IV (how expensive relative to IV itself)
        signal:          'sell_premium' | 'buy_options' | 'neutral'
        interpretation:  Plain-text reasoning

    The vol premium is the core question. Options buyers pay IV; if RV turns out
    lower than IV, sellers win. The vol premium is the seller's edge on average —
    options tend to overprice vol by a few points historically (the "variance risk
    premium"). But this mean is small relative to variance, so position sizing matters.
    """
    premium = atm_implied_vol - realized_vol
    premium_pct = (premium / atm_implied_vol * 100) if atm_implied_vol > 0 else 0.0

    if premium > 0.03:  # IV > RV by more than 3 points
        signal = "sell_premium"
        interp = (
            f"IV ({atm_implied_vol:.1%}) is {premium:.1%} above realized vol "
            f"({realized_vol:.1%}) — options overpriced vs history. "
            "Edge: sell premium (collect the variance risk premium)."
        )
    elif premium < -0.03:  # IV < RV by more than 3 points
        signal = "buy_options"
        interp = (
            f"IV ({atm_implied_vol:.1%}) is {abs(premium):.1%} *below* realized vol "
            f"({realized_vol:.1%}) — options cheap vs recent history. "
            "Edge: buy options for cheap directional exposure or protection."
        )
    else:
        signal = "neutral"
        interp = (
            f"IV ({atm_implied_vol:.1%}) and realized vol ({realized_vol:.1%}) are "
            "close — no strong vol edge. Consider directional or event strategies instead."
        )

    return {
        "iv_pct": round(atm_implied_vol * 100, 1),
        "rv_pct": round(realized_vol * 100, 1),
        "vol_premium_pts": round(premium * 100, 1),
        "vol_premium_pct_of_iv": round(premium_pct, 1),
        "dte": dte,
        "signal": signal,
        "interpretation": interp,
    }


# ── Full surface snapshot ──────────────────────────────────────────────────────

def surface_snapshot(
    chain: "OptionChain",
    realized_vol: float | None = None,
    *,
    target_dte: int = 30,
) -> dict:
    """One-shot surface summary for a ticker: ATM IV, skew, term structure, edge signal.

    Args:
        chain:        Fetched OptionChain.
        realized_vol: Optional realized vol to compare IV against (annualized, e.g. 0.20).
        target_dte:   Preferred DTE for the main IV read (nearest expiry within 7d of this).

    Returns a dict suitable for agent injection or dashboard display.
    """
    if chain.spot is None:
        return {"ticker": chain.ticker, "error": "no spot price — cannot build surface"}

    # Find the expiry closest to target_dte
    ts = term_structure(chain)
    target_expiry = None
    if ts:
        target_expiry = min(
            [r for r in ts if r["dte"] is not None and r["dte"] >= 7],
            key=lambda r: abs(r["dte"] - target_dte),
            default=None,
        )

    main_iv: float | None = None
    skew_result: dict = {}
    if target_expiry:
        calls, puts = chain.for_expiry(target_expiry["expiry"])
        main_iv = target_expiry["atm_iv"]
        skew_result = iv_skew(calls, puts, chain.spot)

    edge: dict = {}
    if main_iv is not None and realized_vol is not None:
        dte = target_expiry["dte"] if target_expiry else target_dte
        edge = iv_vs_rv(main_iv, realized_vol, dte=dte)

    return {
        "ticker": chain.ticker,
        "spot": chain.spot,
        "source": chain.source,
        "fetched_at": chain.fetched_at,
        "target_expiry": target_expiry["expiry"] if target_expiry else None,
        "target_dte": target_expiry["dte"] if target_expiry else None,
        "atm_iv_pct": round(main_iv * 100, 1) if main_iv is not None else None,
        "skew": skew_result or None,
        "term_structure": ts,
        "edge": edge or None,
        "errors": chain.errors,
    }

"""Options short-premium backtest — the money metric for the options desk.

The strategist recommends *selling* defined-risk premium when implied vol looks
rich. The thesis behind that is the **variance risk premium (VRP)**: implied vol
(what you sell at) tends to exceed the volatility the underlying subsequently
*realizes* (what actually happens). This module asks the honest question the
recommendation can't: would systematically selling that structure have made money,
after costs, across history?

Honest data note — this is the crux:
  To measure the VRP you need the *implied* vol you sold at AND the *realized* path
  that followed. Free sources don't carry historical option chains, but they DO
  carry **VIX**, which is the market's 30-day implied vol for SPX/SPY. So we price
  each entry's legs with Black-Scholes using **VIX as the entry implied vol** (real
  historical IV) and settle them against the **actual underlying price at expiry**
  (real realized outcome). For SPY/index this is a faithful VRP backtest. For single
  names VIX is a systematic proxy (their IV is usually higher/noisier) — so treat
  single-name results as indicative, not precise, and prefer SPY/QQQ/IWM.

What it is NOT: it does not model skew, early assignment, intraday management, or
real bid/ask — entry costs are a configurable haircut. It captures the *structural*
edge (premium collected vs realized moves), which is exactly the desk's thesis.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from orgos.options.pricer import bs_greeks, bs_price

_EMPTY = {
    "n_trades": 0, "win_rate": None, "total_pnl": None, "avg_pnl": None,
    "avg_credit": None, "return_on_risk": None, "sharpe": None, "max_dd": None,
    "pct_expired_otm": None,
}


def _select_short_put_strike(S: float, sigma: float, T: float, r: float,
                             target_delta: float) -> float:
    """Strike whose short-put delta is closest to ``target_delta`` (e.g. 0.30).

    Scans strikes from 60%–100% of spot and picks the nearest by |delta|. Rounding
    to whole dollars matches how listed strikes actually trade for index ETFs.
    """
    best_k, best_err = S, 1e9
    for k in range(int(S * 0.60), int(S) + 1):
        if k <= 0:
            continue
        d = abs(bs_greeks(S, float(k), T, r, sigma, "put")["delta"])  # 0..0.5 for OTM put
        err = abs(d - target_delta)
        if err < best_err:
            best_k, best_err = float(k), err
    return best_k


def _trade_pnl(S0: float, S_exp: float, sigma: float, *, structure: str,
               dte: int, r: float, target_delta: float, width: float,
               cost_per_contract: float, slippage_frac: float) -> dict | None:
    """P&L of one short-premium trade held to expiry.

    Entry legs priced by BS at ``sigma`` (the implied vol sold). Settlement uses the
    realized ``S_exp`` (intrinsic at expiry). Returns per-trade economics in dollars
    (×100 multiplier), or None if the structure can't be formed.
    """
    T = dte / 365.0
    short_k = _select_short_put_strike(S0, sigma, T, r, target_delta)
    short_prem = bs_price(S0, short_k, T, r, sigma, "put")

    if structure == "cash_secured_put":
        credit = short_prem
        max_loss = short_k - credit                       # if it goes to zero
        payoff = max(0.0, short_k - S_exp)                # what you owe at expiry
    elif structure == "put_spread":
        long_k = short_k - width
        if long_k <= 0:
            return None
        long_prem = bs_price(S0, long_k, T, r, sigma, "put")
        credit = short_prem - long_prem                   # net credit collected
        max_loss = width - credit                         # defined risk
        payoff = max(0.0, short_k - S_exp) - max(0.0, long_k - S_exp)
    else:
        raise ValueError(f"unknown structure {structure!r}")

    if credit <= 0 or max_loss <= 0:
        return None

    # Per-share economics scale by the ×100 multiplier; the flat per-contract
    # commission does NOT (it's already a dollar amount). Slippage is a haircut on
    # the credit, also per-share.
    legs = 1 if structure == "cash_secured_put" else 2
    gross = (credit - payoff) * 100.0                     # ×100 option multiplier
    slippage = slippage_frac * credit * 100.0
    commission = cost_per_contract * legs                 # flat $ per leg
    pnl = gross - slippage - commission
    return {
        "short_k": short_k, "credit": round(credit, 4), "max_loss": round(max_loss, 4),
        "payoff": round(payoff, 4), "pnl": round(pnl, 2),
        "expired_otm": payoff == 0.0,
    }


def backtest_short_premium(
    prices: pd.Series, vix: pd.Series, *, structure: str = "put_spread",
    dte: int = 30, target_delta: float = 0.30, width: float = 5.0,
    r: float = 0.04, cost_per_contract: float = 0.65, slippage_frac: float = 0.02,
    iv_scale: float = 1.0,
) -> dict:
    """Walk a short-premium strategy across history; report after-cost economics.

    On a rolling schedule (every ``dte`` trading days, non-overlapping) sell the
    structure at ``target_delta``, priced at that day's VIX (× ``iv_scale``) as
    implied vol, and settle against the underlying ``dte`` calendar days later.

    iv_scale lets you bump VIX for single names whose IV runs richer than the index
    (e.g. 1.3); keep 1.0 for SPY/QQQ/IWM where VIX is the right implied vol.
    """
    df = pd.concat([prices.rename("px"), vix.rename("vix")], axis=1).dropna()
    if len(df) < dte + 20:
        return dict(_EMPTY, note="insufficient overlapping price/VIX history")

    px = df["px"].to_numpy(float)
    iv = (df["vix"].to_numpy(float) / 100.0) * iv_scale
    n = len(df)

    trades: list[dict] = []
    i = 0
    step = max(dte, 1)
    while i + dte < n:
        S0, S_exp, sigma = px[i], px[i + dte], iv[i]
        if sigma > 0:
            t = _trade_pnl(S0, S_exp, sigma, structure=structure, dte=dte, r=r,
                           target_delta=target_delta, width=width,
                           cost_per_contract=cost_per_contract,
                           slippage_frac=slippage_frac)
            if t is not None:
                t["entry_date"] = str(df.index[i].date()) if hasattr(df.index[i], "date") else str(df.index[i])
                trades.append(t)
        i += step

    return _summarize(trades)


def _summarize(trades: list[dict]) -> dict:
    if not trades:
        return dict(_EMPTY, note="no trades formed")
    pnls = np.array([t["pnl"] for t in trades], float)
    credits = np.array([t["credit"] for t in trades], float)
    risks = np.array([t["max_loss"] for t in trades], float)
    wins = pnls > 0
    cum = np.cumsum(pnls)
    dd = float((cum - np.maximum.accumulate(cum)).min())
    # annualize the Sharpe from per-trade P&L using trades/year implied by ~21d/mo
    sharpe = float(pnls.mean() / pnls.std() * np.sqrt(len(pnls))) if pnls.std() > 0 else None
    return {
        "n_trades": int(len(trades)),
        "win_rate": round(float(wins.mean()), 3),
        "total_pnl": round(float(pnls.sum()), 2),
        "avg_pnl": round(float(pnls.mean()), 2),
        "avg_credit": round(float(credits.mean()), 4),
        # P&L earned per dollar of risk put up across all trades (after costs)
        "return_on_risk": round(float(pnls.sum() / (risks.sum() * 100.0)), 4),
        "sharpe": round(sharpe, 3) if sharpe is not None else None,
        "max_dd": round(dd, 2),
        "pct_expired_otm": round(float(np.mean([t["expired_otm"] for t in trades])), 3),
    }


def run_backtest(ticker: str, *, lookback_days: int = 1000, **kw) -> dict:
    """Convenience entry: fetch prices + VIX for ``ticker`` and backtest.

    Returns the metrics dict plus the inputs used, or an error dict if data is short.
    """
    from orgos.quant.marketdata import get_prices, MarketDataError
    from orgos.quant.volatility import fetch_vix

    ticker = ticker.upper()
    try:
        prices = get_prices(ticker, lookback_days=lookback_days)
    except MarketDataError as exc:
        return {"ticker": ticker, "error": f"no price data: {exc}"}
    vix = fetch_vix(lookback_days=lookback_days)
    if vix.empty:
        return {"ticker": ticker, "error": "no VIX data"}

    result = backtest_short_premium(prices, vix, **kw)
    return {
        "ticker": ticker,
        "structure": kw.get("structure", "put_spread"),
        "dte": kw.get("dte", 30),
        "target_delta": kw.get("target_delta", 0.30),
        "iv_source": "VIX" + (f"×{kw['iv_scale']}" if kw.get("iv_scale", 1.0) != 1.0 else ""),
        **result,
    }

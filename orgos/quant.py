"""Deterministic cointegration engine — the quant desk's core compute.

Engle-Granger on REAL adjusted prices: align two series → OLS hedge ratio →
ADF test on the spread → half-life of mean reversion. No LLM touches the math
(the report's rule: deterministic tools for finance, not the model). Prices come
from orgos.marketdata; the LLM's job is only to choose the universe and read the
ranked output.
"""

from __future__ import annotations

import itertools
import warnings

import numpy as np
import pandas as pd

from .marketdata import MarketDataError, get_prices

_MIN_OVERLAP = 60  # need enough common observations for a meaningful ADF test


def _coint_from_series(
    s1: pd.Series, s2: pd.Series, t1: str, t2: str
) -> dict:
    """Engle-Granger on two already-fetched adjusted-close series."""
    warnings.filterwarnings("ignore")
    df = pd.concat([s1, s2], axis=1, join="inner").dropna()
    if len(df) < _MIN_OVERLAP:
        return {"ticker1": t1, "ticker2": t2,
                "error": f"insufficient overlap ({len(df)} days)"}

    a = df.iloc[:, 0].to_numpy(dtype=float)
    b = df.iloc[:, 1].to_numpy(dtype=float)
    n = len(a)

    # Step 1: OLS hedge ratio  b ≈ alpha + beta*a
    X = np.column_stack([np.ones(n), a])
    alpha, beta = np.linalg.lstsq(X, b, rcond=None)[0]
    spread = b - (alpha + beta * a)

    # Step 2: ADF test on the spread (stationary spread ⇒ cointegrated)
    from statsmodels.tsa.stattools import adfuller

    adf = adfuller(spread, maxlag=int((n - 1) ** (1 / 3)), autolag="AIC")
    pvalue = float(adf[1])
    adf_stat = float(adf[0])
    is_stationary = pvalue < 0.05

    # Step 3: half-life of mean reversion via AR(1) on the spread
    spread_lag = spread[:-1]
    spread_diff = np.diff(spread)
    gamma = np.linalg.lstsq(
        np.column_stack([np.ones(len(spread_lag)), spread_lag]), spread_diff, rcond=None
    )[0][1]
    half_life = round(float(-np.log(2) / gamma), 1) if gamma < 0 else None

    cointegrated = bool(is_stationary and half_life is not None)
    verdict = (
        f"Cointegrated (half-life={half_life}d)" if cointegrated
        else "Stationary but half-life N/A" if is_stationary
        else "Not cointegrated"
    )
    return {
        "ticker1": t1, "ticker2": t2, "n_obs": n,
        "hedge_ratio": round(float(beta), 4),
        "adf_stat": round(adf_stat, 4), "adf_pvalue": round(pvalue, 4),
        "half_life_days": half_life, "cointegrated": cointegrated,
        "verdict": verdict,
    }


def cointegration_test(ticker1: str, ticker2: str, lookback_days: int = 504) -> dict:
    """Fetch both tickers and run the Engle-Granger test on the real pair."""
    try:
        p1 = get_prices(ticker1, lookback_days)
        p2 = get_prices(ticker2, lookback_days)
    except MarketDataError as exc:
        return {"ticker1": ticker1, "ticker2": ticker2, "error": str(exc)}
    return _coint_from_series(p1, p2, ticker1, ticker2)


def scan_universe(
    tickers: list[str],
    lookback_days: int = 504,
    *,
    max_half_life: float | None = 30.0,
    min_half_life: float = 1.0,
) -> dict:
    """Test every pair in a universe and rank the cointegrated, tradeable ones.

    Prices are fetched once per ticker (not per pair) so the cost is O(N) fetches
    for O(N²) tests. "Tradeable" filters half-life into [min_half_life,
    max_half_life] — too fast is noise, too slow ties up capital.
    """
    prices: dict[str, pd.Series | None] = {}
    unavailable: list[str] = []
    for t in tickers:
        try:
            prices[t] = get_prices(t, lookback_days)
        except MarketDataError:
            prices[t] = None
            unavailable.append(t)

    tested = 0
    candidates: list[dict] = []
    for t1, t2 in itertools.combinations(tickers, 2):
        if prices.get(t1) is None or prices.get(t2) is None:
            continue
        res = _coint_from_series(prices[t1], prices[t2], t1, t2)
        if "error" in res:
            continue
        tested += 1
        if res["cointegrated"]:
            hl = res["half_life_days"]
            if hl is not None and min_half_life <= hl <= (max_half_life or float("inf")):
                candidates.append(res)

    candidates.sort(key=lambda r: (r["half_life_days"], r["adf_pvalue"]))
    return {
        "universe": tickers,
        "lookback_days": lookback_days,
        "pairs_tested": tested,
        "tradeable_pairs": candidates,
        "unavailable_tickers": unavailable,
    }

"""Market data — pluggable EOD price provider for the quant desk.

Tiingo primary (CRSP-style adjusted close, correct on the free tier), yfinance
fallback. Same shape as the search backend: auto-select by available key, fall
through on error/empty.

It returns the split- AND dividend-ADJUSTED close. That is the only series safe
for cointegration: an unadjusted dividend puts an artificial drop on the ex-date,
which the ADF test reads as a structural break → a spurious cointegration signal
→ a trade that loses immediately. (This is exactly why Stooq/Finnhub-free were
rejected for this use case — they don't dividend-adjust on the free tier.)
"""

from __future__ import annotations

import datetime as dt
import os
from typing import Any, Callable

import pandas as pd

# Provider contract: (ticker, start_iso, end_iso, key) -> adjusted-close Series.
Provider = Callable[[str, str, str, "str | None"], pd.Series]


class MarketDataError(Exception):
    """Raised when no provider can return prices for a ticker."""


def _tiingo_prices(ticker: str, start: str, end: str, key: str | None) -> pd.Series:
    import httpx

    resp = httpx.get(
        f"https://api.tiingo.com/tiingo/daily/{ticker}/prices",
        params={"startDate": start, "endDate": end, "token": key},
        headers={"Content-Type": "application/json"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if not data:
        return pd.Series(dtype=float)
    # adjClose carries split + dividend adjustment (the series we want).
    s = pd.Series({row["date"][:10]: row["adjClose"] for row in data}, dtype=float)
    s.index = pd.to_datetime(s.index)
    s = s.sort_index()
    s.name = ticker
    return s


def _polygon_prices(ticker: str, start: str, end: str, key: str | None) -> pd.Series:
    import httpx

    resp = httpx.get(
        f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/day/{start}/{end}",
        params={"adjusted": "true", "sort": "asc", "limit": 50000, "apiKey": key},
        timeout=30,
    )
    resp.raise_for_status()
    results = resp.json().get("results") or []
    if not results:
        return pd.Series(dtype=float)
    # 't' is an epoch-ms timestamp; 'c' is the split+dividend adjusted close.
    idx = pd.to_datetime([r["t"] for r in results], unit="ms")
    s = pd.Series([r["c"] for r in results], index=idx, dtype=float).sort_index()
    s.name = ticker
    return s


def _yfinance_prices(ticker: str, start: str, end: str, key: str | None) -> pd.Series:
    import yfinance as yf

    # auto_adjust=True → Close is split+dividend adjusted (matches Tiingo adjClose).
    df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
    if df is None or df.empty:
        return pd.Series(dtype=float)
    close = df["Close"]
    if isinstance(close, pd.DataFrame):  # yfinance returns a multiindex for some calls
        close = close.iloc[:, 0]
    close = close.astype(float)
    close.name = ticker
    return close


# Tiingo primary (free, correct adjustment); Polygon as the higher-quality
# cross-check/fallback (institutional Layer-1, free 5 req/min); yfinance the
# no-key last resort. Each is skipped if its key is absent.
_PROVIDERS: list[tuple[str, str | None, Provider]] = [
    ("tiingo", "TIINGO_API_KEY", _tiingo_prices),
    ("polygon", "POLYGON_API_KEY", _polygon_prices),
    ("yfinance", None, _yfinance_prices),
]


def _run_providers(
    ticker: str, start_iso: str, end_iso: str,
    providers: list[tuple[str, str | None, Provider]],
) -> tuple[str, pd.Series, list[str]]:
    """Try each provider for an explicit date range; first non-empty wins.

    Skips keyed providers with no key, falls through on error OR empty.
    Raises MarketDataError if all fail.
    """
    errors: list[str] = []
    for name, env_key, fn in providers:
        key = os.environ.get(env_key) if env_key else None
        if env_key is not None and not key:
            continue
        try:
            s = fn(ticker, start_iso, end_iso, key)
            if s is not None and len(s) > 0:
                return name, s, errors
            errors.append(f"{name}: empty")
        except Exception as exc:  # noqa: BLE001 — try the next provider
            errors.append(f"{name}: {type(exc).__name__}: {str(exc)[:120]}")
    raise MarketDataError(f"no price data for {ticker!r}: {errors}")


def get_prices_with_source(
    ticker: str,
    lookback_days: int = 504,
    *,
    end: dt.date | None = None,
    providers: list[tuple[str, str | None, Provider]] | None = None,
) -> tuple[str, pd.Series, list[str]]:
    """Fetch an adjusted-close series by lookback, trying providers in order.

    ``lookback_days`` is in *trading* days; we request extra calendar days and
    trim to the tail.
    """
    end = end or dt.date.today()
    # ~1.6 calendar days per trading day, plus a buffer for holidays/weekends.
    start = end - dt.timedelta(days=int(lookback_days * 1.6) + 14)
    name, s, errors = _run_providers(
        ticker, start.isoformat(), end.isoformat(), providers or _PROVIDERS
    )
    return name, s.tail(lookback_days), errors


def get_prices_range_with_source(
    ticker: str, start: dt.date, end: dt.date,
    *, providers: list[tuple[str, str | None, Provider]] | None = None,
) -> tuple[str, pd.Series, list[str]]:
    """Fetch an adjusted-close series for an explicit [start, end] date range.

    Used by the bars cache for incremental top-ups (fetch only missing dates).
    """
    return _run_providers(
        ticker, start.isoformat(), end.isoformat(), providers or _PROVIDERS
    )


def get_prices(ticker: str, lookback_days: int = 504, **kw: Any) -> pd.Series:
    """Adjusted-close series for one ticker (provider chosen automatically)."""
    _, series, _ = get_prices_with_source(ticker, lookback_days, **kw)
    return series


def get_prices_range(ticker: str, start: dt.date, end: dt.date, **kw: Any) -> pd.Series:
    """Adjusted-close series for an explicit date range (provider auto-chosen)."""
    _, series, _ = get_prices_range_with_source(ticker, start, end, **kw)
    return series

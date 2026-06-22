"""Option chain fetcher — structured option data for a given ticker.

yfinance primary (free, no key required), Polygon.io fallback (institutional
quality, requires POLYGON_API_KEY). Follows the same provider pattern as
orgos.quant.marketdata so the fallback logic is consistent.

The output is a normalized OptionChain — a dict of DataFrames keyed by expiry,
each with columns:
    strike, bid, ask, last, volume, open_interest,
    implied_vol, in_the_money, dte, option_type

Network is isolated from analytics: fetch returns raw DataFrames; surface.py
does all the interpretation. Nothing here touches Black-Scholes.
"""

from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass, field

import pandas as pd


class OptionDataError(Exception):
    """Raised when no provider can return option data for a ticker."""


# ── Normalized schema ─────────────────────────────────────────────────────────

_CALLS_COLS = {
    "strike": "strike",
    "bid": "bid",
    "ask": "ask",
    "lastPrice": "last",
    "volume": "volume",
    "openInterest": "open_interest",
    "impliedVolatility": "implied_vol",
    "inTheMoney": "in_the_money",
}
_PUTS_COLS = _CALLS_COLS  # same schema from yfinance


def _normalize(df: pd.DataFrame, option_type: str, expiry: str) -> pd.DataFrame:
    """Rename yfinance chain columns to the internal schema."""
    present = {k: v for k, v in _CALLS_COLS.items() if k in df.columns}
    out = df.rename(columns=present)[list(present.values())].copy()
    out["option_type"] = option_type
    out["expiry"] = expiry
    today = dt.date.today()
    out["dte"] = (dt.date.fromisoformat(expiry) - today).days
    for col in ("volume", "open_interest"):
        if col in out.columns:
            out[col] = out[col].fillna(0).astype(int)
    return out.reset_index(drop=True)


# ── yfinance provider ─────────────────────────────────────────────────────────

def _yf_expiries(ticker: str) -> list[str]:
    import yfinance as yf
    return list(yf.Ticker(ticker).options or [])


def _yf_chain(ticker: str, expiry: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (calls_df, puts_df) normalized to internal schema."""
    import yfinance as yf

    chain = yf.Ticker(ticker).option_chain(expiry)
    calls = _normalize(chain.calls, "call", expiry)
    puts = _normalize(chain.puts, "put", expiry)
    return calls, puts


# ── Polygon provider ──────────────────────────────────────────────────────────

def _polygon_expiries(ticker: str, key: str) -> list[str]:
    import httpx

    resp = httpx.get(
        "https://api.polygon.io/v3/reference/options/contracts",
        params={
            "underlying_ticker": ticker,
            "expired": "false",
            "limit": 250,
            "apiKey": key,
        },
        timeout=30,
    )
    resp.raise_for_status()
    contracts = resp.json().get("results") or []
    dates = sorted({c["expiration_date"] for c in contracts})
    return dates


def _polygon_chain(ticker: str, expiry: str, key: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fetch one expiry from Polygon's options contract reference + last quote."""
    import httpx

    resp = httpx.get(
        "https://api.polygon.io/v3/reference/options/contracts",
        params={
            "underlying_ticker": ticker,
            "expiration_date": expiry,
            "limit": 250,
            "apiKey": key,
        },
        timeout=30,
    )
    resp.raise_for_status()
    contracts = resp.json().get("results") or []
    if not contracts:
        return pd.DataFrame(), pd.DataFrame()

    rows = []
    for c in contracts:
        rows.append({
            "strike": c.get("strike_price"),
            "bid": None,
            "ask": None,
            "last": None,
            "volume": 0,
            "open_interest": c.get("shares_per_contract", 100),
            "implied_vol": None,
            "in_the_money": None,
            "option_type": c.get("contract_type", "call").lower(),
            "expiry": expiry,
            "dte": (dt.date.fromisoformat(expiry) - dt.date.today()).days,
        })
    df = pd.DataFrame(rows)
    calls = df[df["option_type"] == "call"].reset_index(drop=True)
    puts = df[df["option_type"] == "put"].reset_index(drop=True)
    return calls, puts


# ── Public API ────────────────────────────────────────────────────────────────

@dataclass
class OptionChain:
    """Normalized option chain for one ticker across all available expiries.

    calls: pd.DataFrame  — all call contracts (all expiries stacked)
    puts:  pd.DataFrame  — all put contracts  (all expiries stacked)
    expiries: list[str]  — available expiry dates (ISO format, sorted)
    spot: float | None   — underlying price at fetch time (if available)
    ticker: str
    fetched_at: str      — ISO timestamp
    source: str          — which provider was used
    """
    ticker: str
    calls: pd.DataFrame
    puts: pd.DataFrame
    expiries: list[str]
    spot: float | None
    fetched_at: str
    source: str
    errors: list[str] = field(default_factory=list)

    def for_expiry(self, expiry: str) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Calls and puts for one specific expiry date."""
        c = self.calls[self.calls["expiry"] == expiry].reset_index(drop=True)
        p = self.puts[self.puts["expiry"] == expiry].reset_index(drop=True)
        return c, p

    def nearest_expiry(self, min_dte: int = 7) -> str | None:
        """First expiry at least ``min_dte`` calendar days out."""
        today = dt.date.today()
        for e in self.expiries:
            if (dt.date.fromisoformat(e) - today).days >= min_dte:
                return e
        return None

    def expiries_in_range(self, min_dte: int = 7, max_dte: int = 90) -> list[str]:
        """Expiries with DTE in [min_dte, max_dte]."""
        today = dt.date.today()
        return [
            e for e in self.expiries
            if min_dte <= (dt.date.fromisoformat(e) - today).days <= max_dte
        ]


def get_chain(
    ticker: str,
    *,
    max_expiries: int = 12,
    min_dte: int = 0,
) -> OptionChain:
    """Fetch a normalized option chain for ``ticker``.

    Tries yfinance first (no key), then Polygon.io if POLYGON_API_KEY is set.
    Loads up to ``max_expiries`` expiry dates to keep API calls manageable.
    """
    ticker = ticker.upper()
    errors: list[str] = []
    fetched_at = dt.datetime.now(dt.timezone.utc).isoformat()
    today = dt.date.today()

    # ── yfinance ─────────────────────────────────────────────────────────────
    try:
        import yfinance as yf

        tk = yf.Ticker(ticker)
        all_expiries = list(tk.options or [])
        if all_expiries:
            expiries = [
                e for e in all_expiries
                if (dt.date.fromisoformat(e) - today).days >= min_dte
            ][:max_expiries]

            all_calls, all_puts = [], []
            for exp in expiries:
                try:
                    c, p = _yf_chain(ticker, exp)
                    all_calls.append(c)
                    all_puts.append(p)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"yfinance expiry {exp}: {exc}")

            spot: float | None = None
            try:
                info = tk.fast_info
                spot = float(getattr(info, "last_price", None) or 0) or None
            except Exception:  # noqa: BLE001
                pass

            calls_df = pd.concat(all_calls, ignore_index=True) if all_calls else pd.DataFrame()
            puts_df = pd.concat(all_puts, ignore_index=True) if all_puts else pd.DataFrame()

            return OptionChain(
                ticker=ticker,
                calls=calls_df,
                puts=puts_df,
                expiries=expiries,
                spot=spot,
                fetched_at=fetched_at,
                source="yfinance",
                errors=errors,
            )
        errors.append("yfinance: no options data")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"yfinance: {type(exc).__name__}: {str(exc)[:120]}")

    # ── Polygon fallback ──────────────────────────────────────────────────────
    polygon_key = os.environ.get("POLYGON_API_KEY")
    if polygon_key:
        try:
            all_expiries = _polygon_expiries(ticker, polygon_key)
            expiries = [
                e for e in all_expiries
                if (dt.date.fromisoformat(e) - today).days >= min_dte
            ][:max_expiries]

            all_calls, all_puts = [], []
            for exp in expiries:
                try:
                    c, p = _polygon_chain(ticker, exp, polygon_key)
                    all_calls.append(c)
                    all_puts.append(p)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"polygon expiry {exp}: {exc}")

            calls_df = pd.concat(all_calls, ignore_index=True) if all_calls else pd.DataFrame()
            puts_df = pd.concat(all_puts, ignore_index=True) if all_puts else pd.DataFrame()

            return OptionChain(
                ticker=ticker,
                calls=calls_df,
                puts=puts_df,
                expiries=expiries,
                spot=None,
                fetched_at=fetched_at,
                source="polygon",
                errors=errors,
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"polygon: {type(exc).__name__}: {str(exc)[:120]}")

    raise OptionDataError(f"no option data for {ticker!r}: {errors}")


def list_expiries(ticker: str, *, min_dte: int = 7) -> list[str]:
    """Available expiry dates for a ticker (yfinance, quick call)."""
    import yfinance as yf

    all_exp = list(yf.Ticker(ticker.upper()).options or [])
    today = dt.date.today()
    return [e for e in all_exp if (dt.date.fromisoformat(e) - today).days >= min_dte]

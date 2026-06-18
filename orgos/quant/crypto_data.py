"""Crypto daily-bars cache — ccxt OHLCV, cached, incremental.

The data layer for crypto cointegration discovery. Fetches daily closes via
ccxt (same library Icarus trades through, so the data matches what it executes
on) and caches them in local SQLite — pay once, top up the tail. Crypto needs no
split/dividend adjustment, so the raw close is the right series.

Exchange defaults to binance (override EXCHANGE_NAME — Icarus's own var) and
USDT quote. Public OHLCV needs no API key. Why crypto: less-efficient markets +
faster regimes mean more genuine, less-crowded cointegration than liquid US
equities — the deliberate bet behind pointing the engine here.
"""

from __future__ import annotations

import datetime as dt
import os
import sqlite3
import time
from contextlib import contextmanager

import pandas as pd

DB_PATH = "./_orgos_memory/crypto_bars.db"
QUOTE = os.environ.get("CRYPTO_QUOTE", "USDT")

# Liquid, exchange-listed coins with enough history for cointegration. BTC is
# the market factor (the crypto analog of SPY) — kept out of the tradeable set.
DEFAULT_UNIVERSE = [
    "ETH", "BNB", "SOL", "XRP", "ADA", "AVAX", "DOGE", "DOT", "LINK", "MATIC",
    "LTC", "BCH", "ATOM", "UNI", "ETC", "FIL", "APT", "ARB", "OP", "NEAR",
]
FACTOR = "BTC"


class CryptoDataError(Exception):
    """Raised when an exchange returns no usable data for a symbol."""


_EXCHANGE = None


def _exchange():
    global _EXCHANGE
    if _EXCHANGE is None:
        import ccxt

        name = os.environ.get("EXCHANGE_NAME", "binance")
        _EXCHANGE = getattr(ccxt, name)({"enableRateLimit": True})
    return _EXCHANGE


@contextmanager
def _conn(db_path: str = DB_PATH):
    from pathlib import Path

    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def ensure_table(db_path: str = DB_PATH) -> None:
    with _conn(db_path) as con:
        con.execute(
            "CREATE TABLE IF NOT EXISTS crypto_bars ("
            "symbol TEXT NOT NULL, date TEXT NOT NULL, close REAL NOT NULL, "
            "exchange TEXT NOT NULL, fetched_at TEXT NOT NULL DEFAULT (datetime('now')), "
            "PRIMARY KEY (symbol, date))"
        )


def _fetch_ohlcv_closes(symbol: str, since_ms: int) -> pd.Series:
    """Daily closes for SYMBOL/QUOTE from `since_ms` to now (ccxt, public)."""
    ex = _exchange()
    market = f"{symbol}/{QUOTE}"
    rows = ex.fetch_ohlcv(market, timeframe="1d", since=since_ms, limit=1000)
    if not rows:
        return pd.Series(dtype=float)
    # ccxt OHLCV row: [ts_ms, open, high, low, close, volume]
    idx = pd.to_datetime([r[0] for r in rows], unit="ms").normalize()
    s = pd.Series([float(r[4]) for r in rows], index=idx, dtype=float)
    s = s[~s.index.duplicated(keep="last")].sort_index()
    s.name = symbol
    return s


def cached_max_dates(symbols: list[str], db_path: str = DB_PATH) -> dict[str, dt.date]:
    if not symbols:
        return {}
    ensure_table(db_path)
    q = ("SELECT symbol, max(date) FROM crypto_bars "
         f"WHERE symbol IN ({','.join('?' * len(symbols))}) GROUP BY symbol")
    with _conn(db_path) as con:
        return {s: dt.date.fromisoformat(d)
                for s, d in con.execute(q, list(symbols)).fetchall() if d}


def _upsert(symbol: str, series: pd.Series, exchange: str, db_path: str = DB_PATH) -> int:
    records = [
        (symbol, (idx.date() if hasattr(idx, "date") else idx).isoformat(),
         float(val), exchange)
        for idx, val in series.items() if pd.notna(val)
    ]
    if not records:
        return 0
    with _conn(db_path) as con:
        con.executemany(
            "INSERT INTO crypto_bars (symbol, date, close, exchange) VALUES (?,?,?,?) "
            "ON CONFLICT(symbol, date) DO UPDATE SET close=excluded.close, "
            "exchange=excluded.exchange, fetched_at=datetime('now')",
            records,
        )
    return len(records)


def refresh(
    symbols: list[str], lookback_days: int = 365, *,
    end: dt.date | None = None, db_path: str = DB_PATH,
) -> dict:
    """Ensure each symbol's cache covers ~[end-lookback, end]; fetch only the gap."""
    ensure_table(db_path)
    end = end or dt.date.today()
    full_start = end - dt.timedelta(days=lookback_days + 5)
    have = cached_max_dates(symbols, db_path)
    exchange = os.environ.get("EXCHANGE_NAME", "binance")

    written: dict[str, int] = {}
    errors: dict[str, str] = {}
    for sym in symbols:
        last = have.get(sym)
        start = full_start if last is None else last + dt.timedelta(days=1)
        if start > end:
            written[sym] = 0
            continue
        since_ms = int(time.mktime(start.timetuple()) * 1000)
        try:
            series = _fetch_ohlcv_closes(sym, since_ms)
            written[sym] = _upsert(sym, series, exchange, db_path)
        except Exception as exc:  # noqa: BLE001 — record, keep going
            errors[sym] = f"{type(exc).__name__}: {str(exc)[:120]}"
    return {"written": written, "errors": errors, "exchange": exchange,
            "as_of": end.isoformat()}


def get_cached_panel(
    symbols: list[str], lookback_days: int = 365, *,
    end: dt.date | None = None, db_path: str = DB_PATH,
) -> pd.DataFrame:
    if not symbols:
        return pd.DataFrame()
    ensure_table(db_path)
    end = end or dt.date.today()
    start = end - dt.timedelta(days=lookback_days + 5)
    q = ("SELECT symbol, date, close FROM crypto_bars "
         f"WHERE symbol IN ({','.join('?' * len(symbols))}) "
         "AND date BETWEEN ? AND ? ORDER BY date")
    with _conn(db_path) as con:
        data = con.execute(q, [*symbols, start.isoformat(), end.isoformat()]).fetchall()
    if not data:
        return pd.DataFrame()
    df = pd.DataFrame(data, columns=["symbol", "date", "close"])
    panel = df.pivot(index="date", columns="symbol", values="close")
    panel.index = pd.to_datetime(panel.index)
    return panel.sort_index().tail(lookback_days)


def get_panel(
    symbols: list[str], lookback_days: int = 365, *,
    refresh_cache: bool = True, end: dt.date | None = None, db_path: str = DB_PATH,
) -> pd.DataFrame:
    """Refresh (incrementally) then return the crypto price panel for scanning."""
    if refresh_cache:
        refresh(symbols, lookback_days, end=end, db_path=db_path)
    return get_cached_panel(symbols, lookback_days, end=end, db_path=db_path)

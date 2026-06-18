"""Daily bars cache — pay once for adjusted EOD, top up incrementally.

The data skill behind the scanner. Adjusted daily closes (Tiingo, via the
marketdata layer) are cached in a LOCAL SQLite store, so a repeated scan never
re-pays for history it already has — only the missing tail is fetched. Source-
agnostic: each row records which provider it came from.

Local SQLite (not Icarus's DB) on purpose: the trading DB's app user has no
CREATE privilege (good security), and keeping the cache local means orgos never
writes to the live trading DB — it stays purely Icarus's. The stored series is
the dividend+split-ADJUSTED close — the series cointegration requires.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from contextlib import contextmanager
from pathlib import Path

import pandas as pd

from .marketdata import MarketDataError, get_prices_range

DB_PATH = Path("./_orgos_memory/bars.db")

_CREATE = """
CREATE TABLE IF NOT EXISTS bars_daily (
    symbol      TEXT NOT NULL,
    date        TEXT NOT NULL,
    adj_close   REAL NOT NULL,
    source      TEXT NOT NULL,
    fetched_at  TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (symbol, date)
)
"""


@contextmanager
def _conn(db_path: Path | str = DB_PATH):
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def ensure_table(db_path: Path | str = DB_PATH) -> None:
    with _conn(db_path) as con:
        con.execute(_CREATE)


def cached_max_dates(symbols: list[str], db_path: Path | str = DB_PATH) -> dict[str, dt.date]:
    """Latest cached date per symbol (missing symbols absent from the dict)."""
    if not symbols:
        return {}
    ensure_table(db_path)
    q = ("SELECT symbol, max(date) FROM bars_daily "
         f"WHERE symbol IN ({','.join('?' * len(symbols))}) GROUP BY symbol")
    with _conn(db_path) as con:
        out = {}
        for sym, d in con.execute(q, list(symbols)).fetchall():
            if d:
                out[sym] = dt.date.fromisoformat(d)
        return out


def _upsert(symbol: str, series: pd.Series, source: str,
            db_path: Path | str = DB_PATH) -> int:
    """Insert/update adjusted closes for one symbol. Returns rows written."""
    records = [
        (symbol,
         (idx.date() if hasattr(idx, "date") else idx).isoformat(),
         float(val), source)
        for idx, val in series.items()
        if pd.notna(val)
    ]
    if not records:
        return 0
    with _conn(db_path) as con:
        con.executemany(
            "INSERT INTO bars_daily (symbol, date, adj_close, source) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(symbol, date) DO UPDATE SET "
            "adj_close = excluded.adj_close, source = excluded.source, "
            "fetched_at = datetime('now')",
            records,
        )
    return len(records)


def refresh(
    symbols: list[str], lookback_days: int = 504, *,
    end: dt.date | None = None, db_path: Path | str = DB_PATH,
) -> dict:
    """Ensure each symbol's cache covers [end-lookback, end], fetching only gaps.

    First-time symbols get the full lookback; already-cached symbols fetch only
    from the day after their latest cached date — the incremental top-up that
    keeps Tiingo calls (and cost) minimal.
    """
    ensure_table(db_path)
    end = end or dt.date.today()
    full_start = end - dt.timedelta(days=int(lookback_days * 1.6) + 14)
    have = cached_max_dates(symbols, db_path)

    written: dict[str, int] = {}
    errors: dict[str, str] = {}
    for sym in symbols:
        last = have.get(sym)
        start = full_start if last is None else last + dt.timedelta(days=1)
        if start > end:
            written[sym] = 0  # cache already current
            continue
        try:
            series = get_prices_range(sym, start, end)
            written[sym] = _upsert(sym, series, "tiingo", db_path)
        except MarketDataError as exc:
            errors[sym] = str(exc)
    return {"written": written, "errors": errors,
            "symbols": len(symbols), "as_of": end.isoformat()}


def get_cached_panel(
    symbols: list[str], lookback_days: int = 504, *,
    end: dt.date | None = None, db_path: Path | str = DB_PATH,
) -> pd.DataFrame:
    """Return a price panel (columns = symbols, index = date) straight from cache."""
    if not symbols:
        return pd.DataFrame()
    ensure_table(db_path)
    end = end or dt.date.today()
    start = end - dt.timedelta(days=int(lookback_days * 1.6) + 14)
    q = ("SELECT symbol, date, adj_close FROM bars_daily "
         f"WHERE symbol IN ({','.join('?' * len(symbols))}) "
         "AND date BETWEEN ? AND ? ORDER BY date")
    with _conn(db_path) as con:
        data = con.execute(q, [*symbols, start.isoformat(), end.isoformat()]).fetchall()
    if not data:
        return pd.DataFrame()
    df = pd.DataFrame(data, columns=["symbol", "date", "adj_close"])
    panel = df.pivot(index="date", columns="symbol", values="adj_close")
    panel.index = pd.to_datetime(panel.index)
    # Trim to the last `lookback_days` trading rows so the cache path is
    # equivalent to the direct get_prices path (which tails the same count) —
    # otherwise the *1.6 calendar buffer over-includes history and shifts the
    # cointegration window, giving different results for the "same" lookback.
    return panel.sort_index().tail(lookback_days)


def get_panel(
    symbols: list[str], lookback_days: int = 504, *,
    refresh_cache: bool = True, end: dt.date | None = None,
    db_path: Path | str = DB_PATH,
) -> pd.DataFrame:
    """Top-level: refresh the cache (incrementally) then return the price panel.

    This is the scanner skill's data entry point — cheap on repeat calls because
    only the missing tail is fetched from the provider.
    """
    if refresh_cache:
        refresh(symbols, lookback_days, end=end, db_path=db_path)
    return get_cached_panel(symbols, lookback_days, end=end, db_path=db_path)

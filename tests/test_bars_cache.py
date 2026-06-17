"""Tests for the incremental bars cache (offline — DB and provider mocked)."""

import datetime as dt

import pandas as pd
import pytest

from orgos import bars_cache


@pytest.fixture
def captured(monkeypatch):
    """Stub out the DB + provider; capture what refresh() decides to fetch."""
    calls = {"fetched": [], "upserts": []}

    monkeypatch.setattr(bars_cache, "ensure_table", lambda *a, **k: None)

    def fake_range(sym, start, end, **kw):
        calls["fetched"].append((sym, start, end))
        idx = pd.date_range(start, end, freq="B")
        return pd.Series(range(1, len(idx) + 1), index=idx, dtype=float)

    def fake_upsert(sym, series, source, *a, **k):
        calls["upserts"].append((sym, len(series), source))
        return len(series)

    monkeypatch.setattr(bars_cache, "get_prices_range", fake_range)
    monkeypatch.setattr(bars_cache, "_upsert", fake_upsert)
    return calls


class TestIncrementalRefresh:
    def test_new_symbol_fetches_full_lookback(self, captured, monkeypatch):
        monkeypatch.setattr(bars_cache, "cached_max_dates", lambda syms, *a, **k: {})
        end = dt.date(2026, 6, 17)
        bars_cache.refresh(["NEW"], lookback_days=100, end=end)
        sym, start, got_end = captured["fetched"][0]
        assert sym == "NEW" and got_end == end
        assert start < end - dt.timedelta(days=100)   # full lookback window

    def test_cached_symbol_fetches_only_gap(self, captured, monkeypatch):
        last = dt.date(2026, 6, 10)
        monkeypatch.setattr(bars_cache, "cached_max_dates", lambda syms, *a, **k: {"OLD": last})
        end = dt.date(2026, 6, 17)
        bars_cache.refresh(["OLD"], lookback_days=100, end=end)
        sym, start, got_end = captured["fetched"][0]
        assert start == last + dt.timedelta(days=1)    # day after last cached
        assert got_end == end

    def test_current_cache_skips_fetch(self, captured, monkeypatch):
        monkeypatch.setattr(bars_cache, "cached_max_dates",
                            lambda syms, *a, **k: {"CUR": dt.date(2026, 6, 17)})
        out = bars_cache.refresh(["CUR"], lookback_days=100, end=dt.date(2026, 6, 17))
        assert captured["fetched"] == []               # nothing fetched
        assert out["written"]["CUR"] == 0

    def test_provider_error_recorded_not_raised(self, captured, monkeypatch):
        from orgos.marketdata import MarketDataError

        monkeypatch.setattr(bars_cache, "cached_max_dates", lambda syms, *a, **k: {})

        def boom(sym, start, end, **kw):
            raise MarketDataError("no data for BAD")

        monkeypatch.setattr(bars_cache, "get_prices_range", boom)
        out = bars_cache.refresh(["BAD"], end=dt.date(2026, 6, 17))
        assert "BAD" in out["errors"]
        assert out["written"] == {}


class TestSqliteRoundTrip:
    """Against a real temp SQLite db — write, dedupe, read back as a panel."""

    def test_nan_values_dropped(self, tmp_path):
        db = tmp_path / "bars.db"
        bars_cache.ensure_table(db)
        idx = pd.to_datetime(["2026-06-10", "2026-06-11", "2026-06-12"])
        series = pd.Series([10.0, float("nan"), 12.0], index=idx)
        assert bars_cache._upsert("X", series, "tiingo", db) == 2  # NaN dropped

    def test_upsert_then_panel_roundtrip(self, tmp_path):
        db = tmp_path / "bars.db"
        bars_cache.ensure_table(db)
        idx = pd.date_range("2026-01-01", periods=10, freq="B")
        bars_cache._upsert("AAA", pd.Series(range(1, 11), index=idx, dtype=float), "tiingo", db)
        bars_cache._upsert("BBB", pd.Series(range(11, 21), index=idx, dtype=float), "tiingo", db)
        panel = bars_cache.get_cached_panel(["AAA", "BBB"], 504, end=dt.date(2026, 1, 20), db_path=db)
        assert list(panel.columns) == ["AAA", "BBB"]
        assert len(panel) == 10

    def test_upsert_is_idempotent(self, tmp_path):
        db = tmp_path / "bars.db"
        bars_cache.ensure_table(db)
        idx = pd.date_range("2026-01-01", periods=5, freq="B")
        s = pd.Series(range(1, 6), index=idx, dtype=float)
        bars_cache._upsert("AAA", s, "tiingo", db)
        bars_cache._upsert("AAA", s, "tiingo", db)  # same dates again
        panel = bars_cache.get_cached_panel(["AAA"], 504, end=dt.date(2026, 1, 10), db_path=db)
        assert len(panel) == 5                          # no duplicate rows

    def test_cached_max_dates_reflects_writes(self, tmp_path):
        db = tmp_path / "bars.db"
        bars_cache.ensure_table(db)
        idx = pd.date_range("2026-01-01", periods=5, freq="B")
        bars_cache._upsert("AAA", pd.Series(range(5), index=idx, dtype=float), "tiingo", db)
        out = bars_cache.cached_max_dates(["AAA", "MISSING"], db)
        assert out["AAA"] == idx[-1].date()
        assert "MISSING" not in out

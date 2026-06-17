"""Tests for the quant engine + market-data provider layer (offline)."""

import numpy as np
import pandas as pd
import pytest

from orgos.marketdata import MarketDataError, get_prices_with_source
from orgos.quant import _coint_from_series, scan_universe


def _series(values, start="2023-01-01"):
    idx = pd.date_range(start, periods=len(values), freq="B")
    return pd.Series(values, index=idx, dtype=float)


class TestCointegrationMath:
    """Engle-Granger correctness on constructed series with a known answer."""

    def test_cointegrated_pair_detected(self):
        rng = np.random.default_rng(0)
        n = 400
        common = rng.normal(0, 1, n).cumsum()          # shared stochastic trend
        s1 = _series(100 + common + rng.normal(0, 0.5, n))
        s2 = _series(50 + 0.5 * common + rng.normal(0, 0.5, n))  # stationary spread
        res = _coint_from_series(s1, s2, "A", "B")
        assert res["cointegrated"] is True
        assert res["adf_pvalue"] < 0.05
        assert res["half_life_days"] is not None
        assert abs(res["hedge_ratio"] - 0.5) < 0.1     # OLS recovers the true ratio

    def test_independent_walks_not_cointegrated(self):
        rng = np.random.default_rng(7)
        n = 400
        s1 = _series(100 + rng.normal(0, 1, n).cumsum())
        s2 = _series(100 + rng.normal(0, 1, n).cumsum())  # independent walk
        res = _coint_from_series(s1, s2, "A", "B")
        assert res["cointegrated"] is False

    def test_insufficient_overlap_errors(self):
        s1 = _series([1, 2, 3, 4, 5], start="2023-01-01")
        s2 = _series([5, 4, 3, 2, 1], start="2024-01-01")  # no overlapping dates
        res = _coint_from_series(s1, s2, "A", "B")
        assert "error" in res


class TestMarketDataFallback:
    """Provider layer: priority order, keyless skip, empty/​error fallthrough."""

    @staticmethod
    def _good(t, s, e, k):
        return pd.Series([1.0, 2.0, 3.0], index=pd.date_range("2023-01-01", periods=3))

    @staticmethod
    def _empty(t, s, e, k):
        return pd.Series(dtype=float)

    @staticmethod
    def _boom(t, s, e, k):
        raise ValueError("provider down")

    def test_empty_falls_through(self):
        providers = [("a", None, self._empty), ("b", None, self._good)]
        name, series, errs = get_prices_with_source("X", 3, providers=providers)
        assert name == "b" and len(series) == 3
        assert any("empty" in e for e in errs)

    def test_keyless_provider_skipped(self, monkeypatch):
        monkeypatch.delenv("NOPE_KEY", raising=False)
        providers = [("keyed", "NOPE_KEY", self._boom), ("b", None, self._good)]
        name, _, _ = get_prices_with_source("X", 3, providers=providers)
        assert name == "b"  # keyed provider skipped (no key), never called _boom

    def test_error_falls_through(self):
        providers = [("a", None, self._boom), ("b", None, self._good)]
        name, _, errs = get_prices_with_source("X", 3, providers=providers)
        assert name == "b"
        assert any("ValueError" in e for e in errs)

    def test_all_fail_raises(self):
        providers = [("a", None, self._boom)]
        with pytest.raises(MarketDataError):
            get_prices_with_source("X", 3, providers=providers)


class TestScanUniverse:
    """scan_universe ranks tradeable pairs and tolerates unavailable tickers."""

    def test_unavailable_ticker_tolerated(self, monkeypatch):
        import orgos.quant as quant

        def fake_get_prices(ticker, lookback_days=504, **kw):
            if ticker == "BAD":
                raise MarketDataError("no data")
            rng = np.random.default_rng(hash(ticker) % 1000)
            return _series(100 + rng.normal(0, 1, 300).cumsum())

        monkeypatch.setattr(quant, "get_prices", fake_get_prices)
        res = scan_universe(["GOOD1", "GOOD2", "BAD"], 300)
        assert "BAD" in res["unavailable_tickers"]
        assert res["pairs_tested"] >= 1  # GOOD1/GOOD2 still tested

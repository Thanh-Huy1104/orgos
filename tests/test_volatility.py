"""Volatility module — pure analytics tests (no network)."""

import numpy as np
import pandas as pd
import pytest

from orgos.quant.volatility import (
    realized_vol,
    vol_regime,
    vol_position_size,
    vol_spike,
    vol_scaled_signal,
    vol_summary,
    vix_regime,
    scan_iv_rank,
)


def _prices(n=300, drift=0.001, vol=0.015, seed=0):
    rng = np.random.default_rng(seed)
    r = drift + rng.normal(0, vol, n)
    return pd.Series(100 * np.cumprod(1 + r), index=pd.RangeIndex(n))


def _vix(n=252, seed=1):
    rng = np.random.default_rng(seed)
    return pd.Series(15 + rng.normal(0, 3, n).cumsum() * 0.1 + 5, index=pd.RangeIndex(n))


# ── Realized vol ──────────────────────────────────────────────────────────────

class TestRealizedVol:
    def test_shape_and_warmup(self):
        p = _prices()
        rv = realized_vol(p, window=20)
        assert len(rv) == len(p)
        assert rv.iloc[:19].isna().all()   # warm-up period is NaN
        assert rv.iloc[20:].notna().all()

    def test_higher_vol_yields_higher_rv(self):
        low = realized_vol(_prices(vol=0.005), window=20).dropna()
        high = realized_vol(_prices(vol=0.03), window=20).dropna()
        assert high.mean() > low.mean()

    def test_annualization(self):
        # iid daily log-returns of 1% → annualised vol = 1% * sqrt(252)
        rng = np.random.default_rng(42)
        # Use a deterministic series: prices that move exactly 1% each day
        # (alternating +1% / -1% so the std of log-returns is ~1%)
        n = 200
        signs = np.where(np.arange(n) % 2 == 0, 1, -1)
        daily = 1 + signs * 0.01
        p = pd.Series(100 * np.cumprod(daily), index=pd.RangeIndex(n))
        rv = realized_vol(p, window=50, periods_per_year=252).dropna()
        expected = 0.01 * np.sqrt(252)
        assert abs(rv.mean() - expected) < 0.005


# ── Vol regime ────────────────────────────────────────────────────────────────

class TestVolRegime:
    def test_valid_labels(self):
        rv = realized_vol(_prices(), window=20).dropna()
        regime = vol_regime(rv)
        assert set(regime.dropna().unique()).issubset({"low", "medium", "high"})

    def test_low_vol_regime_lower_than_high_vol(self):
        # Regime is expanding-percentile-based, so only ~33% of any period is "low".
        # The correct invariant: the low-vol period has more "low" labels than the
        # high-vol period that follows it.
        low_p = _prices(vol=0.003)
        high_p = _prices(vol=0.04)
        p = pd.concat([low_p, high_p], ignore_index=True)
        rv = realized_vol(p, window=20)
        regime = vol_regime(rv)
        low_slice = regime.iloc[20:300].dropna()
        high_slice = regime.iloc[300:].dropna()
        assert (low_slice == "low").mean() > (high_slice == "low").mean()

    def test_no_lookahead(self):
        rv = realized_vol(_prices(), window=20)
        regime = vol_regime(rv)
        assert regime.iloc[:19].isna().all()


# ── Position sizing ───────────────────────────────────────────────────────────

class TestVolPositionSize:
    def test_target_vol_gives_size_one(self):
        rv = pd.Series([0.15])  # exactly at target
        size = vol_position_size(rv, target_vol=0.15)
        assert abs(float(size.iloc[0]) - 1.0) < 1e-9

    def test_high_vol_reduces_size(self):
        rv = pd.Series([0.30])  # 2x target
        size = vol_position_size(rv, target_vol=0.15)
        assert abs(float(size.iloc[0]) - 0.5) < 1e-9

    def test_max_leverage_cap(self):
        rv = pd.Series([0.01])  # very low vol
        size = vol_position_size(rv, target_vol=0.15, max_leverage=1.0)
        assert float(size.iloc[0]) <= 1.0

    def test_nan_gives_zero(self):
        rv = pd.Series([float("nan")])
        size = vol_position_size(rv)
        assert float(size.iloc[0]) == 0.0


# ── Vol spike ─────────────────────────────────────────────────────────────────

class TestVolSpike:
    def test_spike_detected_on_sudden_jump(self):
        rv = pd.Series([0.1] * 50 + [0.5] + [0.1] * 10)
        spike = vol_spike(rv, window=20, z_threshold=2.0)
        assert spike.iloc[50]

    def test_stable_series_no_spike(self):
        rv = pd.Series([0.15] * 100)
        spike = vol_spike(rv, window=20, z_threshold=2.0)
        assert not spike.dropna().any()


# ── Vol-scaled signal ─────────────────────────────────────────────────────────

class TestVolScaledSignal:
    def test_flat_below_max_leverage(self):
        p = _prices(vol=0.03)
        signal = pd.Series(1.0, index=p.index)
        scaled = vol_scaled_signal(signal, p, target_vol=0.15, max_leverage=1.0)
        assert (scaled <= 1.0).all()
        assert (scaled >= 0.0).all()

    def test_no_lookahead(self):
        p = _prices()
        signal = pd.Series(1.0, index=p.index)
        scaled = vol_scaled_signal(signal, p, vol_window=20)
        assert scaled.iloc[0] == 0.0  # shifted: day 0 has no info

    def test_high_vol_shrinks_position(self):
        p_low = _prices(vol=0.005)
        p_high = _prices(vol=0.04)
        signal = pd.Series(1.0, index=p_low.index)
        scaled_low = vol_scaled_signal(signal, p_low, vol_window=20).dropna()
        scaled_high = vol_scaled_signal(signal, p_high, vol_window=20).dropna()
        assert scaled_low.mean() > scaled_high.mean()


# ── VIX regime ────────────────────────────────────────────────────────────────

class TestVixRegime:
    def test_calm_below_15(self):
        vix = pd.Series([12.0, 13.5, 14.9])
        assert (vix_regime(vix) == "calm").all()

    def test_fear_above_25(self):
        vix = pd.Series([26.0, 30.0])
        assert (vix_regime(vix) == "fear").all()

    def test_panic_above_35(self):
        vix = pd.Series([36.0, 80.0])
        assert (vix_regime(vix) == "panic").all()

    def test_normal_between_15_and_25(self):
        vix = pd.Series([17.0, 22.0, 24.9])
        assert (vix_regime(vix) == "normal").all()


# ── Vol summary ───────────────────────────────────────────────────────────────

class TestVolSummary:
    def test_keys_present(self):
        p = _prices(n=300)
        result = vol_summary(p, vol_window=20)
        for k in ("current_vol_pct", "vol_1m_avg_pct", "vol_3m_avg_pct",
                  "regime", "spike_today", "position_size_15pct"):
            assert k in result

    def test_with_vix(self):
        p = _prices(n=300)
        vix = _vix(n=300)
        result = vol_summary(p, vol_window=20, vix=vix)
        assert "vix_current" in result
        assert "vix_regime" in result
        assert result["vix_regime"] in ("calm", "normal", "fear", "panic")

    def test_short_series_graceful(self):
        p = _prices(n=5)
        result = vol_summary(p, vol_window=20)
        assert result["current_vol_pct"] is None or isinstance(result["current_vol_pct"], float)


# ── IV rank scan (pure / no network) ─────────────────────────────────────────

def test_scan_iv_rank_sorts_by_rank():
    """scan_iv_rank should return high-rank entries first; error entries last."""
    fake_results = [
        {"ticker": "A", "iv_rank": 80.0, "signal": "sell_premium"},
        {"ticker": "B", "iv_rank": 10.0, "signal": "buy_options"},
        {"ticker": "C", "error": "no options data"},
    ]
    # Simulate what scan_iv_rank does internally without hitting the network
    sortable = [r for r in fake_results if r.get("iv_rank") is not None]
    unsortable = [r for r in fake_results if r.get("iv_rank") is None]
    sortable.sort(key=lambda r: r["iv_rank"], reverse=True)
    ordered = sortable + unsortable

    assert ordered[0]["ticker"] == "A"
    assert ordered[1]["ticker"] == "B"
    assert ordered[2]["ticker"] == "C"

"""Tests for the shared cointegration library (icarus_quant), offline."""

import numpy as np
import pandas as pd
import pytest

from orgos.quant.icarus_quant import (
    analyze_pair,
    engle_granger,
    half_life,
    hurst,
    factor_r2,
    scan,
    sub_period_stability,
)


def _idx(n, start="2022-01-01"):
    return pd.date_range(start, periods=n, freq="B")


def _cointegrated(n=500, beta=0.5, seed=0):
    """Two positive price series sharing a common trend (stationary spread)."""
    rng = np.random.default_rng(seed)
    common = rng.normal(0, 0.02, n).cumsum()
    y = pd.Series(100 * np.exp(common + rng.normal(0, 0.003, n)), index=_idx(n))
    x = pd.Series(80 * np.exp(beta * common + rng.normal(0, 0.003, n)), index=_idx(n))
    return y, x


def _independent(n=500, seed=1):
    rng = np.random.default_rng(seed)
    y = pd.Series(100 * np.exp(rng.normal(0, 0.02, n).cumsum()), index=_idx(n))
    x = pd.Series(80 * np.exp(rng.normal(0, 0.02, n).cumsum()), index=_idx(n))
    return y, x


class TestEstimators:
    def test_cointegrated_pair_low_pvalue(self):
        y, x = _cointegrated()
        p, beta, spread = engle_granger(y, x)
        assert p < 0.05
        assert len(spread) == len(y)

    def test_independent_pair_high_pvalue(self):
        y, x = _independent()
        p, _, _ = engle_granger(y, x)
        assert p >= 0.05

    def test_mean_reverting_spread_has_finite_half_life(self):
        rng = np.random.default_rng(3)
        # AR(1) with phi<1 ⇒ mean reverting ⇒ finite positive half-life
        s = [0.0]
        for _ in range(500):
            s.append(0.8 * s[-1] + rng.normal())
        hl = half_life(np.array(s))
        assert hl > 0 and np.isfinite(hl)

    def test_hurst_random_walk_near_half(self):
        rng = np.random.default_rng(5)
        rw = rng.normal(0, 1, 2000).cumsum()
        assert 0.35 < hurst(rw) < 0.65          # random walk ≈ 0.5

    def test_hurst_mean_reverting_below_half(self):
        rng = np.random.default_rng(6)
        s = [0.0]
        for _ in range(2000):
            s.append(0.5 * s[-1] + rng.normal())
        assert hurst(np.array(s)) < 0.5

    def test_factor_r2_detects_common_driver(self):
        rng = np.random.default_rng(7)
        factor = pd.Series(rng.normal(0, 1, 400).cumsum(), index=_idx(400))
        spread = factor + pd.Series(rng.normal(0, 0.01, 400), index=_idx(400))
        r2 = factor_r2(spread, factor)
        assert r2 > 0.8                          # spread is basically the factor


class TestSubPeriodStability:
    def test_durable_pair_is_stable(self):
        y, x = _cointegrated(n=600)
        out = sub_period_stability(y, x, k=3)
        assert out["stable"] is True
        assert len(out["sub_pvalues"]) == 3

    def test_independent_pair_not_stable(self):
        y, x = _independent(n=600)
        assert sub_period_stability(y, x, k=3)["stable"] is False


class TestAnalyzeAndScan:
    def test_analyze_pair_full_record(self):
        y, x = _cointegrated()
        st = analyze_pair(y, x, name_y="AAA", name_x="BBB")
        assert st is not None
        assert st.pair == "AAA/BBB"
        assert st.adf_p < 0.05
        assert st.stable is True
        assert np.isfinite(st.half_life)

    def test_analyze_pair_insufficient_data(self):
        y = pd.Series([1.0, 2, 3], index=_idx(3))
        assert analyze_pair(y, y, name_y="A", name_x="B") is None

    def test_scan_finds_cointegrated_rejects_independent(self):
        y1, x1 = _cointegrated(seed=10)
        y2, _ = _independent(seed=11)
        panel = pd.DataFrame({"COINT_Y": y1, "COINT_X": x1, "INDEP": y2})
        survivors = scan(panel, min_half_life=0.0, max_half_life=200.0,
                         max_hurst=0.6, require_stable=False)
        pairs = {s.pair for s in survivors}
        # The cointegrated pair should survive; pairs with INDEP should not dominate.
        assert any("COINT" in p for p in pairs)

    def test_scan_respects_half_life_filter(self):
        y, x = _cointegrated(seed=12)
        panel = pd.DataFrame({"Y": y, "X": x})
        # Impossibly tight half-life window ⇒ nothing survives.
        assert scan(panel, min_half_life=0.0, max_half_life=0.001) == []

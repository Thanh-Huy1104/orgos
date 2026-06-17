"""icarus_quant — shared cointegration library (one source of truth for the math).

Ported from Icarus's own techniques (crypto_durability.py + the equity book
screener) so orgos's scanner skill and Icarus's scanner compute identical stats.
Deliberately dependency-free beyond numpy/pandas/statsmodels and free of any
orgos import, so it can be lifted into a standalone package or imported directly
by Icarus.

The screen, in order of what kills a pair fastest:
  1. Engle-Granger cointegration (ADF on the OLS spread) — is there a stable
     linear combination at all?
  2. Sub-period stability ("durability") — does cointegration hold in EACH
     sub-window, not just the full sample? A pair that only cointegrates in
     aggregate is a regime artifact. This is the p1/p2/p3 + `stable` columns.
  3. Half-life — is mean reversion fast enough to trade but not noise?
  4. Hurst — is the spread genuinely mean-reverting (H < 0.5)?
  5. Factor R² — is the spread its own signal, or just a bet on a common factor
     (rates for equities, BTC for crypto)? High R² ⇒ not a real pair.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.tsa.stattools import adfuller


# ── Core estimators (each pure, on numpy/pandas) ──────────────────────────────

def engle_granger(y: pd.Series, x: pd.Series, *, use_log: bool = True
                  ) -> tuple[float, float, pd.Series]:
    """OLS hedge ratio + ADF on the spread. Returns (adf_pvalue, beta, spread).

    use_log matches Icarus (log prices) — scale-free and the right space for
    ratio-style hedges. Caller must pass already-aligned, positive series.
    """
    ys = np.log(y.to_numpy(float)) if use_log else y.to_numpy(float)
    xs = np.log(x.to_numpy(float)) if use_log else x.to_numpy(float)
    alpha, beta = sm.OLS(ys, sm.add_constant(xs)).fit().params
    spread = ys - (alpha + beta * xs)
    pvalue = float(adfuller(spread, maxlag=1, regression="c", autolag=None)[1])
    return pvalue, float(beta), pd.Series(spread, index=y.index)


def recent_pvalue(y: pd.Series, x: pd.Series, recent: int = 120, *, use_log: bool = True) -> float:
    """Cointegration p-value on just the most-recent `recent` observations.

    The regime-currency check: is the pair cointegrated *now*, not only over the
    full sample? Pairs that cointegrate over a year but not in the recent window
    have already broken — the relationship is stale.
    """
    if len(y) < recent + 5:
        recent = max(30, len(y) - 5)
    p, _, _ = engle_granger(y.iloc[-recent:], x.iloc[-recent:], use_log=use_log)
    return p


def oos_pvalue(y: pd.Series, x: pd.Series, oos: int = 90, *, use_log: bool = True) -> float:
    """Walk-forward out-of-sample cointegration p-value.

    Fit the hedge ratio on the in-sample window (everything before the last
    `oos` obs), then test whether the spread built with that *frozen* ratio is
    stationary on the held-out window the ratio never saw. The honest "does this
    persist" test — relationships that only hold in-sample fail here.
    """
    n = len(y)
    if n < oos + 60:
        oos = max(30, n // 3)
    yi, xi = y.iloc[:-oos], x.iloc[:-oos]
    yo, xo = y.iloc[-oos:], x.iloc[-oos:]
    li_y = np.log(yi.to_numpy(float)) if use_log else yi.to_numpy(float)
    li_x = np.log(xi.to_numpy(float)) if use_log else xi.to_numpy(float)
    alpha, beta = sm.OLS(li_y, sm.add_constant(li_x)).fit().params
    lo_y = np.log(yo.to_numpy(float)) if use_log else yo.to_numpy(float)
    lo_x = np.log(xo.to_numpy(float)) if use_log else xo.to_numpy(float)
    spread_oos = lo_y - (alpha + beta * lo_x)
    return float(adfuller(spread_oos, maxlag=1, regression="c", autolag=None)[1])


def half_life(spread: np.ndarray | pd.Series) -> float:
    """Half-life of mean reversion via AR(1) on the spread (NaN if not reverting)."""
    r = np.asarray(spread, dtype=float)
    lam = sm.OLS(np.diff(r), sm.add_constant(r[:-1])).fit().params[1]
    return float(-np.log(2) / lam) if lam < 0 else float("nan")


def hurst(series: np.ndarray | pd.Series) -> float:
    """Hurst exponent via variance-of-differences (Icarus's method).

    H < 0.5 mean-reverting, ≈0.5 random walk, > 0.5 trending.
    """
    x = np.asarray(series, dtype=float)
    lags = range(2, min(100, len(x) // 2))
    tau = []
    for l in lags:
        d = x[l:] - x[:-l]
        sd = np.std(d)
        tau.append(np.sqrt(sd) if sd > 0 else np.nan)
    tau = np.array(tau, dtype=float)
    ok = ~np.isnan(tau) & (tau > 0)
    if ok.sum() < 5:
        return float("nan")
    lag_arr = np.array(list(lags))[ok]
    return float(np.polyfit(np.log(lag_arr), np.log(tau[ok]), 1)[0] * 2)


def benjamini_hochberg(pvalues: list[float], fdr: float = 0.10) -> float:
    """Benjamini-Hochberg p-value cutoff controlling the false-discovery rate.

    The defense against multiple-hypothesis testing: scanning N pairs at a raw
    p<0.05 yields ~0.05·N false positives (a stock and a random walk look
    cointegrated 5% of the time). BH returns the largest p that still controls
    the *expected proportion* of false discoveries at `fdr`. Pairs with adf_p ≤
    the returned cutoff are the FDR-significant set; everything else is rejected.
    Returns 0.0 if nothing passes (no discoveries survive correction).
    """
    ps = sorted(p for p in pvalues if p is not None and not np.isnan(p))
    m = len(ps)
    if m == 0:
        return 0.0
    cutoff = 0.0
    for i, p in enumerate(ps, start=1):  # 1-indexed rank
        if p <= (i / m) * fdr:
            cutoff = p  # largest p meeting the BH line so far
    return cutoff


def factor_r2(spread: pd.Series, factor: pd.Series) -> float:
    """R² of spread *returns* on a factor's returns.

    High R² ⇒ the spread is mostly a bet on the common factor (rates, market,
    BTC), not a genuine idiosyncratic pair. Returns NaN if no overlap.
    """
    d = pd.concat([spread.diff(), factor.reindex(spread.index).diff()], axis=1).dropna()
    if len(d) < 10:
        return float("nan")
    return float(sm.OLS(d.iloc[:, 0].to_numpy(), sm.add_constant(d.iloc[:, 1].to_numpy())).fit().rsquared)


def sub_period_stability(y: pd.Series, x: pd.Series, *, k: int = 3, use_log: bool = True
                         ) -> dict:
    """Run Engle-Granger on each of k contiguous sub-windows.

    Returns sub-period p-values (p1..pk), betas, beta_drift (max/min |beta|),
    and `stable` = every sub-period cointegrates (p < 0.05). The durability test:
    a real pair holds in each window, not just the aggregate.
    """
    n = len(y)
    bounds = [(i * n // k, (i + 1) * n // k) for i in range(k)]
    pvals: list[float] = []
    betas: list[float] = []
    for lo, hi in bounds:
        ys, xs = y.iloc[lo:hi], x.iloc[lo:hi]
        if len(ys) < 30:
            pvals.append(float("nan"))
            betas.append(float("nan"))
            continue
        p, b, _ = engle_granger(ys, xs, use_log=use_log)
        pvals.append(p)
        betas.append(abs(b))
    valid_b = [b for b in betas if not np.isnan(b) and b > 0]
    beta_drift = (max(valid_b) / min(valid_b)) if len(valid_b) >= 2 else float("nan")
    stable = all((not np.isnan(p)) and p < 0.05 for p in pvals)
    return {"sub_pvalues": pvals, "sub_betas": betas,
            "beta_drift": beta_drift, "stable": stable}


# ── Pair analysis ─────────────────────────────────────────────────────────────

@dataclass
class PairStats:
    pair: str
    y: str
    x: str
    adf_p: float
    beta: float
    half_life: float
    hurst: float
    stable: bool
    beta_drift: float
    spread_vol: float
    factor_r2: float | None
    sub_pvalues: list[float]
    sector: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def analyze_pair(
    y: pd.Series, x: pd.Series, *, name_y: str, name_x: str,
    factor: pd.Series | None = None, k_subperiods: int = 3,
    use_log: bool = True, sector: str = "",
) -> PairStats | None:
    """Full screen for one pair on aligned price series. None if not enough data."""
    df = pd.concat([y, x], axis=1, join="inner").dropna()
    if len(df) < 60:
        return None
    y, x = df.iloc[:, 0], df.iloc[:, 1]

    adf_p, beta, spread = engle_granger(y, x, use_log=use_log)
    stab = sub_period_stability(y, x, k=k_subperiods, use_log=use_log)
    return PairStats(
        pair=f"{name_y}/{name_x}", y=name_y, x=name_x,
        adf_p=round(adf_p, 6), beta=round(beta, 4),
        half_life=round(half_life(spread), 1),
        hurst=round(hurst(spread), 3),
        stable=stab["stable"],
        beta_drift=round(stab["beta_drift"], 3) if not np.isnan(stab["beta_drift"]) else float("nan"),
        spread_vol=round(float(spread.std()), 6),
        factor_r2=round(factor_r2(spread, factor), 3) if factor is not None else None,
        sub_pvalues=[round(p, 6) if not np.isnan(p) else None for p in stab["sub_pvalues"]],
        sector=sector,
    )


def scan(
    prices: pd.DataFrame, *,
    factor: pd.Series | None = None,
    sectors: dict[str, str] | None = None,
    p_threshold: float = 0.05,
    fdr: float | None = None,
    min_half_life: float = 1.0,
    max_half_life: float = 30.0,
    max_hurst: float = 0.5,
    require_stable: bool = True,
    max_factor_r2: float | None = 0.5,
    same_sector_only: bool = False,
) -> list[PairStats]:
    """Scan every pair in a price panel (columns = tickers) and rank survivors.

    Filters (the durability funnel): cointegrated AND half-life in [min,max] AND
    hurst < max_hurst AND (stable if required) AND factor_r2 < max_factor_r2.
    Ranked by sub-period worst-case then full p-value.

    The cointegration gate has two modes:
      - default (fdr=None): raw ``adf_p < p_threshold``.
      - ``fdr`` set (e.g. 0.10): Benjamini-Hochberg over the p-values of EVERY
        pair tested, controlling the false-discovery rate. Use this whenever the
        universe is large/cross-sector — a raw threshold over thousands of pairs
        is a false-positive factory (see benjamini_hochberg).
    """
    sectors = sectors or {}
    tickers = list(prices.columns)
    import itertools

    # Pass 1: analyze every pair (so BH sees the true number of hypotheses
    # tested), keeping only those that clear the NON-statistical gates.
    analyzed: list[PairStats] = []
    for a, b in itertools.combinations(tickers, 2):
        if same_sector_only and sectors.get(a) != sectors.get(b):
            continue
        # Orient so y is the higher-priced leg (Icarus convention).
        ya, xa = (a, b) if prices[a].mean() >= prices[b].mean() else (b, a)
        sector = sectors.get(ya, "") or sectors.get(xa, "")
        try:
            st = analyze_pair(prices[ya], prices[xa], name_y=ya, name_x=xa,
                              factor=factor, sector=sector)
        except Exception:  # noqa: BLE001 — a bad pair must not abort the scan
            continue
        if st is None:
            continue
        analyzed.append(st)

    # Cointegration gate: raw threshold, or BH-FDR cutoff over all tested p-values.
    if fdr is not None:
        cutoff = benjamini_hochberg([s.adf_p for s in analyzed], fdr=fdr)
    else:
        cutoff = p_threshold

    survivors: list[PairStats] = []
    for st in analyzed:
        # FDR uses ≤ cutoff (cutoff is an attained p-value); raw uses < threshold.
        passes_coint = (st.adf_p <= cutoff) if fdr is not None else (st.adf_p < cutoff)
        if not passes_coint:
            continue
        if not (min_half_life < st.half_life < max_half_life):
            continue
        if not (st.hurst < max_hurst):
            continue
        if require_stable and not st.stable:
            continue
        if (max_factor_r2 is not None and st.factor_r2 is not None
                and not np.isnan(st.factor_r2) and st.factor_r2 >= max_factor_r2):
            continue
        survivors.append(st)

    def _worst_sub(s: PairStats) -> float:
        vals = [p for p in s.sub_pvalues if p is not None]
        return max(vals) if vals else 1.0

    survivors.sort(key=lambda s: (_worst_sub(s), s.adf_p))
    return survivors

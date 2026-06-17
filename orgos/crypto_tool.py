"""Crypto cointegration scanner — the discovery skill for digital assets.

Crypto cointegration is REAL but regime-bound (live: 49/171 pairs cointegrate
in-sample, but 0 survive a static year-long stability test). So the durability
test here is NOT the equity 3-subperiod one — it's the recent-window test from
Icarus's crypto_durability.py: a pair must cointegrate over the FULL window AND
the recent ~120 days (regime-current). The edge is "cointegrated now, trade
while it holds, exit fast" — Icarus's OU engine does the holding/exiting.

Rigor layered on top of the broadened search:
  - Benjamini-Hochberg FDR over every pair's full-window p (false-positive
    control across ~190 pairs).
  - BTC-factor independence (reject disguised beta).
  - Hub exclusion ({fil, near, doge}) — crypto_durability.py flags these as
    artifact/meme hubs whose cointegration is often spurious.
  - Walk-forward OOS p-value attached as a CONFIDENCE signal (not a hard gate —
    on real data nothing survives OOS+FDR, so gating on it surfaces nothing;
    it's reported so you can rank by robustness).

Recommend-only. Proposes; never trades.
"""

from __future__ import annotations

import itertools
import json

import numpy as np
import pandas as pd
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from .crypto_data import DEFAULT_UNIVERSE, FACTOR, get_panel
from .icarus_quant import (
    benjamini_hochberg,
    engle_granger,
    factor_r2,
    half_life,
    hurst,
    oos_pvalue,
    recent_pvalue,
)

# Artifact/meme hubs — cointegration involving these is often spurious
# (from Icarus crypto_durability.py). Excluded by default.
HUB_COINS = {"FIL", "NEAR", "DOGE"}

CRYPTO_MAX_HALF_LIFE = 20.0
CRYPTO_MIN_HALF_LIFE = 3.0
CRYPTO_MAX_HURST = 0.45
CRYPTO_MAX_FACTOR_R2 = 0.5
CRYPTO_RECENT_DAYS = 120
CRYPTO_OOS_DAYS = 90
CRYPTO_FDR = 0.10


def run_crypto_scan(
    universe: list[str] | None = None, *, lookback_days: int = 365,
    fdr: float = CRYPTO_FDR, max_half_life: float = CRYPTO_MAX_HALF_LIFE,
    recent_days: int = CRYPTO_RECENT_DAYS, exclude_hubs: bool = True,
    top_n: int = 20, refresh_cache: bool = True,
) -> dict:
    """Fetch cached crypto bars and run the recent-window durability funnel.

    Funnel per pair: full-window cointegration (FDR-gated) AND recent-window
    cointegration AND half-life in band AND Hurst < max AND BTC-independent.
    Walk-forward OOS p attached as a confidence signal. Hubs excluded by default.
    """
    coins = universe or DEFAULT_UNIVERSE
    panel = get_panel(coins + [FACTOR], lookback_days, refresh_cache=refresh_cache)
    if panel.empty:
        return {"error": "no crypto price data available", "universe": coins}

    log_btc = np.log(panel.pop(FACTOR)) if FACTOR in panel.columns else None
    tradeable = [c for c in panel.columns if not (exclude_hubs and c in HUB_COINS)]

    # Pass 1: analyze every pair (so FDR sees the true count of hypotheses).
    analyzed: list[dict] = []
    for a, b in itertools.combinations(tradeable, 2):
        df = pd.concat([panel[a], panel[b]], axis=1, join="inner").dropna()
        if len(df) < 120:
            continue
        ya, xa = (a, b) if df[a].mean() >= df[b].mean() else (b, a)
        y, x = df[ya], df[xa]
        try:
            p_full, beta, spread = engle_granger(y, x)
            rec = {
                "pair": f"{ya}/{xa}", "y": ya, "x": xa, "beta": round(float(beta), 4),
                "adf_p": round(p_full, 6),
                "p_recent": round(recent_pvalue(y, x, recent_days), 6),
                "p_oos": round(oos_pvalue(y, x, CRYPTO_OOS_DAYS), 6),
                "half_life": round(half_life(spread.values), 1),
                "hurst": round(hurst(spread.values), 3),
                "factor_r2": round(factor_r2(spread, log_btc), 3) if log_btc is not None else None,
                "sector": "crypto",
            }
            analyzed.append(rec)
        except Exception:  # noqa: BLE001 — a bad pair must not abort the scan
            continue

    cutoff = benjamini_hochberg([r["adf_p"] for r in analyzed], fdr=fdr)

    survivors = []
    for r in analyzed:
        if r["adf_p"] > cutoff:                                 # FDR (full window)
            continue
        if r["p_recent"] >= 0.05:                               # regime-current
            continue
        if not (CRYPTO_MIN_HALF_LIFE < r["half_life"] < max_half_life):
            continue
        if not (r["hurst"] < CRYPTO_MAX_HURST):
            continue
        fr2 = r["factor_r2"]
        if fr2 is not None and not np.isnan(fr2) and fr2 >= CRYPTO_MAX_FACTOR_R2:
            continue
        # confidence: does it also hold out-of-sample? (signal, not a gate)
        r["oos_confirmed"] = r["p_oos"] < 0.05
        survivors.append(r)

    # Rank: OOS-confirmed first, then by recent-window strength.
    survivors.sort(key=lambda r: (not r["oos_confirmed"], r["p_recent"]))
    n_pairs = len(tradeable) * (len(tradeable) - 1) // 2
    return {
        "asset_class": "crypto", "factor": FACTOR,
        "coins_scanned": tradeable, "hubs_excluded": sorted(HUB_COINS) if exclude_hubs else [],
        "pairs_tested": n_pairs, "fdr": fdr, "fdr_cutoff": round(cutoff, 6),
        "candidates_found": len(survivors),
        "candidates": survivors[:top_n],
    }


class _CryptoScanInput(BaseModel):
    coins: str = Field(
        default="",
        description=("Space/comma-separated coin symbols (e.g. 'ETH SOL AVAX'), "
                     "or empty for the default liquid universe."))
    lookback_days: int = Field(default=365, description="Trading-day lookback (default 365).")
    fdr: float = Field(default=CRYPTO_FDR, description="False-discovery-rate target (default 0.10).")
    top_n: int = Field(default=20, description="Max candidates to return.")


class CryptoScannerTool(BaseTool):
    name: str = "scan_crypto_pairs"
    description: str = (
        "Scan a universe of crypto assets for durable, tradeable cointegrated "
        "pairs. Uses recent-window durability (cointegrated now AND over the full "
        "window), BTC-factor independence, Benjamini-Hochberg FDR, and hub "
        "exclusion. Attaches a walk-forward out-of-sample confidence flag. "
        "Returns a ranked shortlist. Proposes candidates only — it does not trade."
    )
    args_schema: type[BaseModel] = _CryptoScanInput
    tool_category: str = "compute"

    def _run(self, coins: str = "", lookback_days: int = 365,
             fdr: float = CRYPTO_FDR, top_n: int = 20) -> str:
        universe = (
            [c.strip().upper() for c in coins.replace(",", " ").split() if c.strip()]
            or None
        )
        try:
            result = run_crypto_scan(universe, lookback_days=lookback_days,
                                     fdr=fdr, top_n=top_n)
        except Exception as exc:  # noqa: BLE001 — surface, don't crash the agent
            return json.dumps({"error": f"{type(exc).__name__}: {exc}"})
        return json.dumps(result, indent=2, default=str)


def create_crypto_scanner_tool() -> CryptoScannerTool:
    return CryptoScannerTool()

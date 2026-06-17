"""Crypto cointegration scanner — the discovery skill for digital assets.

Wraps the shared math (icarus_quant) over cached crypto bars (crypto_data) with
crypto-appropriate settings: BTC as the market factor (reject pairs that are
just a levered BTC bet), faster mean-reversion band (crypto regimes move in
days, not weeks), and — because the cross-coin universe tests ~190 pairs —
Benjamini-Hochberg FDR instead of a raw p-threshold, so the broadened search
isn't a false-positive factory.

Recommend-only, like the equity scanner. Proposes; never trades.
"""

from __future__ import annotations

import json

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from .crypto_data import DEFAULT_UNIVERSE, FACTOR, get_panel
from .icarus_quant import scan

# Crypto durability gates (looser/faster than equities, per crypto_durability.py):
# regimes move fast → shorter tradeable half-life; mean-reversion bar slightly
# tighter on Hurst; BTC-factor independence so we're not just trading beta.
CRYPTO_MAX_HALF_LIFE = 20.0
CRYPTO_MAX_HURST = 0.45
CRYPTO_MAX_FACTOR_R2 = 0.5
CRYPTO_FDR = 0.10


def run_crypto_scan(
    universe: list[str] | None = None, *, lookback_days: int = 365,
    fdr: float = CRYPTO_FDR, max_half_life: float = CRYPTO_MAX_HALF_LIFE,
    top_n: int = 20, refresh_cache: bool = True,
) -> dict:
    """Fetch cached crypto bars and FDR-scan for durable cointegrated pairs."""
    coins = universe or DEFAULT_UNIVERSE
    panel = get_panel(coins + [FACTOR], lookback_days, refresh_cache=refresh_cache)
    if panel.empty:
        return {"error": "no crypto price data available", "universe": coins}

    factor_series = panel.pop(FACTOR) if FACTOR in panel.columns else None
    sectors = {c: "crypto" for c in panel.columns}
    survivors = scan(
        panel, factor=factor_series, sectors=sectors, fdr=fdr,
        max_half_life=max_half_life, max_hurst=CRYPTO_MAX_HURST,
        max_factor_r2=CRYPTO_MAX_FACTOR_R2,
    )
    n_pairs = len(panel.columns) * (len(panel.columns) - 1) // 2
    return {
        "asset_class": "crypto",
        "factor": FACTOR,
        "coins_scanned": list(panel.columns),
        "pairs_tested": n_pairs,
        "fdr": fdr,
        "candidates_found": len(survivors),
        "candidates": [s.as_dict() for s in survivors[:top_n]],
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
        "pairs. Uses BTC as the market factor and Benjamini-Hochberg FDR to "
        "control false positives across the many pairs tested. Returns a ranked "
        "shortlist with cointegration p-value, half-life, Hurst, and BTC "
        "independence. Proposes candidates only — it does not trade."
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

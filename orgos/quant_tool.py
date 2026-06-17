"""Cointegration scanner — the quant desk's discovery skill (agent-invokable).

Wraps the shared math (icarus_quant) over the cached bars (bars_cache) as a
CrewAI tool an agent can call: give it a universe, it returns a ranked shortlist
of durable, tradeable cointegrated pairs. Read+compute only — it discovers and
proposes; it never trades, sizes, or touches Icarus.

Universes are curated, liquid, single-sector lists (cointegration is a
within-sector phenomenon, and a bounded universe respects the Tiingo free tier).
"""

from __future__ import annotations

import json

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from .bars_cache import get_panel
from .icarus_quant import scan

# Curated liquid universes (single-sector — where cointegration actually lives).
UNIVERSES: dict[str, list[str]] = {
    "utilities": ["DUK", "SO", "DTE", "AEP", "EXC", "XEL", "WEC", "ED", "AEE",
                  "CMS", "FE", "PEG", "ES", "PPL"],
    "staples": ["PG", "KO", "PEP", "WMT", "COST", "CL", "MDLZ", "GIS", "KHC",
                "HSY", "K", "KMB", "CLX"],
    "banks": ["JPM", "BAC", "WFC", "C", "USB", "PNC", "TFC", "GS", "MS", "SCHW"],
    "insurance": ["ALL", "MET", "PRU", "AIG", "TRV", "PGR", "CB", "HIG"],
    "rails": ["UNP", "CSX", "NSC", "CP", "CNI"],
    "energy": ["XOM", "CVX", "COP", "OXY", "SLB", "EOG", "PSX", "VLO"],
    "payments": ["V", "MA", "AXP", "PYPL", "FI", "GPN"],
}

DEFAULT_FACTOR = "SPY"  # market factor for the factor_r2 independence check


def resolve_universe(universe: str) -> tuple[list[str], str]:
    """Resolve a universe name or comma-separated tickers → (tickers, sector).

    A known preset returns its curated list + sector name; otherwise the input
    is treated as an ad-hoc ticker list (sector = 'custom').
    """
    key = universe.strip().lower()
    if key in UNIVERSES:
        return UNIVERSES[key], key
    tickers = [t.strip().upper() for t in universe.replace(",", " ").split() if t.strip()]
    return tickers, "custom"


class _ScanInput(BaseModel):
    universe: str = Field(
        description=("Sector preset (" + ", ".join(UNIVERSES) + ") or a "
                     "space/comma-separated ticker list, e.g. 'DUK SO DTE AEP'."))
    lookback_days: int = Field(default=504, description="Trading-day lookback (default 504 ≈ 2y).")
    max_half_life: float = Field(default=30.0, description="Max mean-reversion half-life in days.")
    top_n: int = Field(default=15, description="Max candidates to return.")


def run_scan(
    universe: str, *, lookback_days: int = 504, max_half_life: float = 30.0,
    top_n: int = 15, factor: str = DEFAULT_FACTOR, refresh_cache: bool = True,
) -> dict:
    """Resolve a universe, pull cached bars, and return ranked candidates.

    Pure-Python entry point (the tool wraps this) so it's testable and reusable
    by a scheduled scan without an agent.
    """
    tickers, sector = resolve_universe(universe)
    if len(tickers) < 2:
        return {"error": f"need >=2 tickers, got {tickers}", "universe": universe}

    panel = get_panel(tickers + [factor], lookback_days, refresh_cache=refresh_cache)
    if panel.empty:
        return {"error": "no price data available", "universe": universe}
    factor_series = panel.pop(factor) if factor in panel.columns else None

    sectors = {t: sector for t in tickers}
    survivors = scan(panel, factor=factor_series, sectors=sectors,
                     max_half_life=max_half_life)
    return {
        "universe": universe,
        "sector": sector,
        "tickers_scanned": list(panel.columns),
        "factor": factor,
        "candidates_found": len(survivors),
        "candidates": [s.as_dict() for s in survivors[:top_n]],
    }


class CointegrationScannerTool(BaseTool):
    name: str = "scan_cointegrated_pairs"
    description: str = (
        "Scan a universe of liquid equities for durable, tradeable cointegrated "
        "pairs. Returns a ranked shortlist with cointegration p-value, half-life, "
        "Hurst, sub-period stability, and factor independence. Use a sector preset "
        "(utilities, staples, banks, insurance, rails, energy, payments) or pass "
        "your own tickers. Proposes candidates only — it does not trade."
    )
    args_schema: type[BaseModel] = _ScanInput
    tool_category: str = "compute"

    def _run(self, universe: str, lookback_days: int = 504,
             max_half_life: float = 30.0, top_n: int = 15) -> str:
        try:
            result = run_scan(universe, lookback_days=lookback_days,
                              max_half_life=max_half_life, top_n=top_n)
        except Exception as exc:  # noqa: BLE001 — surface, don't crash the agent
            return json.dumps({"error": f"{type(exc).__name__}: {exc}"})
        return json.dumps(result, indent=2, default=str)


def create_cointegration_scanner_tool() -> CointegrationScannerTool:
    return CointegrationScannerTool()

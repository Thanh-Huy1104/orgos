"""Deterministic cointegration scan over a universe — no LLM, just the engine.

This is the heart of the quant desk: real adjusted prices (Tiingo primary,
yfinance fallback) → Engle-Granger on every pair → ranked tradeable pairs.
Cheap enough to cron nightly; an LLM is only needed later to choose the universe
and narrate the result.

    export TIINGO_API_KEY=...            # primary data source (free tier)
    python examples/cointegration_scan.py
    python examples/cointegration_scan.py XLE XLF XLK XLV XLI XLY   # custom universe
"""

import sys

from orgos.quant import scan_universe

# Liquid sector ETFs — a scoped universe that fits Tiingo's free tier.
DEFAULT_UNIVERSE = ["XLE", "XLF", "XLK", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE"]


def main() -> None:
    universe = sys.argv[1:] or DEFAULT_UNIVERSE
    print(f"Scanning {len(universe)} tickers "
          f"({len(universe) * (len(universe) - 1) // 2} pairs), 504-day lookback...\n")

    res = scan_universe(universe, lookback_days=504)

    if res["unavailable_tickers"]:
        print(f"⚠ no data for: {', '.join(res['unavailable_tickers'])}\n")

    pairs = res["tradeable_pairs"]
    print(f"{res['pairs_tested']} pairs tested → {len(pairs)} tradeable cointegrated "
          f"(p<0.05, half-life 1–30d)\n")
    if not pairs:
        print("No tradeable cointegrated pairs in this universe right now.")
        return

    print(f"{'PAIR':<14}{'HALF-LIFE':>10}{'ADF p':>10}{'HEDGE β':>10}")
    print("-" * 44)
    for p in pairs:
        pair = f"{p['ticker1']}/{p['ticker2']}"
        print(f"{pair:<14}{str(p['half_life_days']) + 'd':>10}"
              f"{p['adf_pvalue']:>10}{p['hedge_ratio']:>10}")


if __name__ == "__main__":
    main()

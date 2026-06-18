"""Event-driven discovery — a material event surfaces the sector to scan.

The proactive layer on top of the desk. Instead of you choosing a universe, a
*signal* chooses it: a new SEC filing (8-K, merger, etc.) on a ticker we track
points at that ticker's sector, and we run the durability scan + research gate on
that field. The caller must supply an explicit universe → tickers mapping and
sector membership map — no hardcoded presets.

The fuzzy step (which sector does this event implicate?) only PROPOSES the
universe — it's a reverse-lookup of the caller-provided sector map, so a
misread can at worst point the scanner at the wrong sector. The signal itself
(cointegration + the SEC research gate) stays fully deterministic. No trade is
ever fabricated by the trigger.

This first form needs no new external dependency: it reuses sec_edgar (C4),
quant_tool (C3), and research_gate (C4).
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Callable

from .tools.quant_tool import run_scan
from .research_gate import screen_candidates
from .sec_edgar import assess_filings, recent_filings


def ticker_sector(ticker: str, sector_map: dict[str, str]) -> str | None:
    """Look up a ticker's sector in the caller-provided map."""
    return sector_map.get(ticker.strip().upper())


# Filing fetcher is injectable for testing (default = live EDGAR).
FilingsFetcher = Callable[[str], list[dict]]


def _default_fetch(days: int) -> FilingsFetcher:
    return lambda ticker: recent_filings(ticker, days=days)


def detect_events(
    *, lookback_days: int = 7, universes: dict[str, list[str]] | None = None,
    sector_map: dict[str, str] | None = None,
    fetcher: FilingsFetcher | None = None,
) -> list[dict]:
    """Scan tracked tickers for recent material SEC filings.

    universes: sector → tickers mapping. Required — no presets exist.
    sector_map: ticker → sector reverse-lookup map (built by caller).

    Returns one event per ticker that filed something MEDIUM or HIGH risk within
    ``lookback_days``, tagged with the implicated sector.
    """
    if universes is None:
        return []
    if sector_map is None:
        sector_map = {t: s for s, ts in universes.items() for t in ts}
    fetch = fetcher or _default_fetch(lookback_days)
    sectors = list(universes)
    tickers = [t for s in sectors for t in universes.get(s, [])]
    events: list[dict] = []
    for ticker in tickers:
        filings = fetch(ticker)
        a = assess_filings(filings)
        if a["risk"] in ("MEDIUM", "HIGH"):
            events.append({
                "ticker": ticker,
                "sector": ticker_sector(ticker, sector_map),
                "risk": a["risk"],
                "forms": a["high_forms"] + a["medium_forms"],
                "n_filings": a["n_filings"],
            })
    events.sort(key=lambda e: (e["risk"] != "HIGH", e["ticker"]))
    return events


def discover_from_events(
    *, lookback_days: int = 7, event_days: int = 7, gate_days: int = 90,
    universes: dict[str, list[str]] | None = None, scan_lookback: int = 504,
    fetcher: FilingsFetcher | None = None,
    scanner: Any = run_scan, screener: Any = screen_candidates,
) -> dict:
    """End-to-end event-driven discovery.

    universes: sector → tickers mapping. Required — no presets exist.

    1. detect_events → which sectors had a material filing.
    2. For each implicated sector (deduped), run the cointegration scan.
    3. Research-gate the candidates (the gate re-checks each pair's own legs).

    Returns the triggering events plus, per implicated sector, the gated
    recommendation. Recommend-only — nothing is promoted or traded.

    scanner/screener/fetcher are injectable for testing.
    """
    events = detect_events(
        lookback_days=event_days, universes=universes, fetcher=fetcher,
    )
    # Dedupe sectors, preserving HIGH-risk-first order from detect_events.
    triggered_sectors: list[str] = []
    for e in events:
        s = e["sector"]
        if s and s not in triggered_sectors:
            triggered_sectors.append(s)

    results: list[dict] = []
    for sector in triggered_sectors:
        scan = scanner(sector, lookback_days=scan_lookback)
        if scan.get("error") or not scan.get("candidates"):
            results.append({"sector": sector, "candidates_found": 0,
                            "promote": [], "review": [], "hold": []})
            continue
        gated = screener(scan["candidates"], days=gate_days)
        results.append({
            "sector": sector,
            "candidates_found": len(scan["candidates"]),
            "promote": gated["promote"],
            "review": gated["review"],
            "hold": gated["hold"],
        })

    n_promote = sum(len(r["promote"]) for r in results)
    n_review = sum(len(r["review"]) for r in results)
    return {
        "as_of": dt.date.today().isoformat(),
        "events": events,
        "triggered_sectors": triggered_sectors,
        "results": results,
        "summary": (
            f"{len(events)} material filing(s) across "
            f"{len(triggered_sectors)} sector(s) → {n_promote} to promote, "
            f"{n_review} to review."
        ),
    }

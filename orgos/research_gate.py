"""Research gate — vet scanner candidates before recommending promotion.

"Research before doing." A pair clearing the statistical durability screen is
necessary but not sufficient: a pending corporate event (merger, spinoff,
delisting, activist stake) can permanently break the relationship no matter how
clean the history looks. This gate checks each leg's recent SEC filings and turns
the combined picture (stats + filings) into a deterministic recommendation.

Output is a recommendation, never an action — promotion to Icarus's book stays a
human decision (recommend-only). The verdicts:
  HOLD    — a HIGH-risk corporate action is pending on a leg; do not trade.
  REVIEW  — a recent material filing (8-K) warrants a human look.
  PROMOTE — clean filings + strong durable stats; recommend promotion.
"""

from __future__ import annotations

from typing import Any, Callable

from .sec_edgar import assess_filings, recent_filings

# Filing fetcher is injectable for testing (default = live EDGAR).
FilingsFetcher = Callable[[str], list[dict]]


def _default_fetch(days: int) -> FilingsFetcher:
    return lambda ticker: recent_filings(ticker, days=days)


def screen_pair(
    pair_stats: dict, *, days: int = 90, fetcher: FilingsFetcher | None = None,
) -> dict:
    """Build a dossier for one candidate pair: stats + per-leg filing risk + verdict.

    pair_stats is a PairStats.as_dict() (needs 'y', 'x', 'pair', and the screen
    fields). The verdict combines the worst leg's structural risk with the stats.
    """
    fetch = fetcher or _default_fetch(days)
    y, x = pair_stats["y"], pair_stats["x"]

    legs: dict[str, dict] = {}
    worst = "LOW"
    order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
    reasons: list[str] = []
    for leg in (y, x):
        filings = fetch(leg)
        a = assess_filings(filings)
        legs[leg] = a
        if order[a["risk"]] > order[worst]:
            worst = a["risk"]
        if a["high_forms"]:
            reasons.append(f"{leg}: high-risk filings {a['high_forms']}")
        elif a["medium_forms"]:
            reasons.append(f"{leg}: recent {a['medium_forms']}")

    if worst == "HIGH":
        verdict = "HOLD"
        reasons.insert(0, "pending corporate action may break cointegration")
    elif worst == "MEDIUM":
        verdict = "REVIEW"
        reasons.insert(0, "recent material filing — human review advised")
    else:
        verdict = "PROMOTE"
        reasons.insert(0, "clean filings; durable cointegration")

    return {
        "pair": pair_stats["pair"],
        "verdict": verdict,
        "structural_risk": worst,
        "reasons": reasons,
        "stats": {k: pair_stats.get(k) for k in
                  ("adf_p", "half_life", "hurst", "stable", "beta", "beta_drift",
                   "factor_r2", "sub_pvalues", "sector")},
        "leg_filings": legs,
    }


def screen_candidates(
    candidates: list[dict], *, days: int = 90, fetcher: FilingsFetcher | None = None,
) -> dict:
    """Screen a scanner's candidate list; return dossiers grouped by verdict.

    `candidates` is the list under run_scan(...)['candidates']. A shared fetcher
    is reused across calls so the cached ticker→CIK map is hit once.
    """
    fetch = fetcher or _default_fetch(days)
    dossiers = [screen_pair(c, days=days, fetcher=fetch) for c in candidates]
    by = {"PROMOTE": [], "REVIEW": [], "HOLD": []}
    for d in dossiers:
        by[d["verdict"]].append(d)
    return {
        "screened": len(dossiers),
        "promote": by["PROMOTE"],
        "review": by["REVIEW"],
        "hold": by["HOLD"],
        "recommendation": (
            f"{len(by['PROMOTE'])} to promote, {len(by['REVIEW'])} to review, "
            f"{len(by['HOLD'])} on hold"
        ),
    }

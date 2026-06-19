"""Seed the research journal with genuine hunts from this desk's history.

These are real strategist runs — their research trails live in _audit_logs/ under
the run_ids referenced here, so the dashboard's "approach & sources" links resolve
to the actual tool-by-tool trail. Use to (re)populate the Journal for a demo:

    python demo/seed_journal.py
"""

from __future__ import annotations

import json
import sqlite3

from orgos.quant.journal import DB_PATH, _ensure

# (objective, status, score, attempts, tokens, run_id, [attempt_run_ids], ts, summary)
ENTRIES = [
    ("Find non-obvious cointegrated equity pairs outside the same sector — shared commodity or supply-chain links.",
     "completed", 0.9998, 2, 88413, "chain-a470b49d", ["chain-4039f843", "chain-a470b49d"], "2026-06-18T17:40:22",
     "Synthesised three cross-sector theses (Natural Gas E&P × Utilities, Steel × Auto, Refiners × Chemicals). "
     "**All cross-sector hypotheses failed scanning.** The sole durable pair is **AEE/NI** — an intra-sector "
     "Utilities pair: ADF p=0.000199, half-life 7.9d, Hurst 0.232, factor R² 0.036, stable across sub-periods, "
     "OOS Sharpe 2.36, 18.25% return, 100% win rate, −2.59% max drawdown. The cross-sector economic linkages "
     "were sound in theory but did not produce stationary spreads.\n\n**LESSON:** believable economic narratives "
     "do not guarantee cointegration; intra-sector mean reversion dominates."),

    ("Find a durable cointegrated pair among US regulated electric & multi-utility companies",
     "completed", 0.9784, 2, 75477, "chain-bf819fc9", ["chain-146b5152", "chain-bf819fc9"], "2026-06-18T17:33:18",
     "Three novel universes proposed (data-center-exposed, upper-midwest multi-utility, nuclear-heavy), each tested "
     "with the full pipeline (BH-FDR, sub-period stability, SPY-factor independence, half-life bounds) plus a full "
     "S&P 500 Utilities sweep. All novel universes returned **zero durable pairs**; the only survivor sector-wide "
     "is the documented **AEE/NI**. Honest null result for the new theses."),

    ("Find a durable cointegrated pair among US regional banks",
     "needs_revision", None, 2, 49359, "chain-ac5f2423", ["chain-f3b9010f", "chain-ac5f2423"], "2026-06-18T03:52:33",
     "Three bank sub-universes (custody/trust BNY·NTRS·STT, NE super-regionals PNC·MTB·CFG, consumer-finance "
     "COF·SYF), each grounded in current catalysts. The scanner's gates (FDR, sub-period durability, SPY-factor "
     "independence, half-life) eliminated **every** candidate — all failed on high SPY beta and sub-period "
     "instability.\n\n**LESSON:** US bank equities are systematically resistant to cointegration; pivot to "
     "lower-beta sectors (utilities, pipelines, REITs)."),

    ("Find durable cointegrated pairs among S&P 500 utilities.",
     "completed", 0.9958, 1, 89907, "chain-5d363374", ["chain-5d363374"], "2026-06-17T15:02:25",
     "**AEE/NI** (STRONG): ADF p=0.000185, half-life 8.0d, Hurst 0.232, SPY R² 0.036 — Midwestern multi-utilities "
     "with shared gas-distribution exposure. **DTE/SO** (GOOD): ADF p=0.0033, half-life 13.1d. EVRG/NI borderline. "
     "Structural insight: NiSource acts as a cointegration hub for Midwestern multi-utilities. AEE/NI is the "
     "primary actionable candidate."),

    ("Hunt for cointegration between a gold mining ETF (GDX) and a regional bank ETF (KRE). Only scan these two "
     "tickers with a 252-day lookback. If nothing survives, explain why.",
     "completed", 0.9100, 2, 62803, "chain-9eab5840", ["chain-9eab5840"], "2026-06-18T11:55:28",
     "Directed 2-ticker scan of GDX vs KRE. No durable cointegration — gold miners and regional banks have no "
     "shared economic driver and the spread is non-stationary, exactly as economic logic predicts. A clean, "
     "honest negative answer to a specific question."),

    ("Hunt for durable, non-obvious cointegrated pairs among US regional and money-center banks with a clean "
     "economic linkage (deposit base, geography, business mix).",
     "completed", None, 1, 75489, "chain-23b2d0b0", ["chain-23b2d0b0"], "2026-06-17T23:52:19",
     "Eight scanner runs across money-center (JPM·BAC·C·WFC), Great-Lakes super-regionals (FITB·HBAN·KEY) and "
     "Sunbelt (RF·TFC) universes, within- and cross-type, 504d and 252d. **>100 pair-combinations tested; zero "
     "survived** FDR + durability + factor-independence + half-life. Null result is scientifically valid: "
     "factor-adjusted bank spreads are dominated by idiosyncratic noise."),
]


def main() -> None:
    _ensure(DB_PATH)
    con = sqlite3.connect(DB_PATH)
    con.execute("DELETE FROM research_journal")  # idempotent re-seed
    for obj, status, score, attempts, tokens, run_id, attempt_ids, ts, summary in ENTRIES:
        con.execute(
            "INSERT INTO research_journal (ts, objective, status, summary, tokens, run_id, "
            "score, attempts, attempt_run_ids) VALUES (?,?,?,?,?,?,?,?,?)",
            (ts, obj, status, summary, tokens, run_id, score, attempts, json.dumps(attempt_ids)),
        )
    con.commit()
    n = con.execute("SELECT COUNT(*) FROM research_journal").fetchone()[0]
    con.close()
    print(f"seeded {n} journal entries into {DB_PATH}")


if __name__ == "__main__":
    main()

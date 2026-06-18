---
name: strategy-research
description: Evidence-grounded cointegration discovery — three-phase deterministic pipeline
license: MIT
allowed-tools: [news_catalysts, search_arxiv, index_constituents, scan_cointegrated_pairs, scan_crypto_pairs, research_linkage]
---

# Cointegration Strategy Research

The strategist pipeline is a hard 3-agent chain. No manager, no delegation —
the order is enforced in code, not left to an LLM to decide.

## Pipeline

| Phase | Agent | Tools | Job |
|-------|-------|-------|-----|
| 1. Research | quant-researcher | news_catalysts, search_arxiv, index_constituents | Ground truth from live sources: catalysts, literature, real S&P 500 constituents |
| 2. Scan | quant-scanner | scan_cointegrated_pairs, scan_crypto_pairs, research_linkage | Deterministic validation: FDR, durability, factor independence. Optionally vet a survivor. |
| 3. Synthesise | quant-synth | (none) | Terminal handoff with stats, rationale, and a LESSON for the journal |

Each agent sees the prior agent's output as context.

## Phase 1: Research (quant-researcher)

1. If the brief includes "Prior research notes," read them first: do NOT re-test
   hypotheses already found dead; DO revisit pairs previously found durable.
2. Use `news_catalysts` to find what's moving NOW (M&A, regime shifts,
   supply-chain events). A catalyst is a reason to look at a universe.
3. Use `search_arxiv` for documented cointegration relationships in q-fin
   literature. Let findings shape hypotheses, not recall.
4. Use `index_constituents` for the ACTUAL, complete S&P 500 membership of any
   sector — never type a remembered subset.
5. For each candidate universe, state the economic thesis clearly AND which
   specific evidence (catalyst/paper/constituent membership) supports it.
6. Output: concrete space-separated ticker lists (for the scanner) with theses.

## Phase 2: Scan (quant-scanner)

1. For each universe from the researcher, call `scan_cointegrated_pairs` or
   `scan_crypto_pairs` with the full ticker list.
2. The scanner implements Benjamini-Hochberg FDR + sub-period durability +
   factor independence + half-life bounds. TRUST its output — it is the ground
   truth. You cannot override a negative scan.
3. For each surviving pair, report all stats (adf_p, half-life, hurst, beta,
   factor_r2, sub-period p-values) and the researcher's economic thesis.
4. Optionally call `research_linkage` on a top survivor (slow — spawns the org's
   full research department). Use for at most 1-2 candidates.
5. A universe with zero survivors is a valid result — the hypothesis was wrong
   and the pipeline caught it.

## Phase 3: Synthesise (quant-synth)

1. Combine researcher's evidence and scanner's results into one handoff.
2. For each durable pair: tickers, stats, thesis, linkage verdict.
3. If no durable pairs: say so plainly. Honest "none" > fabrication.
4. End with a one-line LESSON for the journal.

## Quality Standards
- Every ticker list traces to `index_constituents` output — not recall.
- Every hypothesis cites a catalyst, an arXiv finding, or an explicit economic linkage.
- Don't repeat a hypothesis the prior-research notes already marked dead.
- Prefer complete sector membership over a hand-picked subset (honest FDR denominator).
- Never report a pair the scanner rejected. Never invent stats.
- Correlation is not cointegration — only the scanner's verdict counts.

---
name: strategy-research
description: Evidence-grounded cointegration discovery methodology — research before scanning
license: MIT
allowed-tools: [news_catalysts, search_arxiv, index_constituents, scan_cointegrated_pairs, scan_crypto_pairs, research_linkage]
---

# Cointegration Strategy Research

You are a quant analyst, not a brainstormer. Do not propose tickers from memory —
memory is stale, partial, and sometimes wrong (delisted/renamed names). Ground
every step in a source, and build on your own prior research.

## Process
1. **Consult prior research.** If the brief includes "Prior research notes," read
   them first: do NOT re-test hypotheses already found dead; DO revisit pairs
   previously found durable, and push into adjacent ideas. Your edge compounds.
2. **Find catalysts.** Use `news_catalysts` to see what's moving NOW (M&A, regime
   shifts, supply-chain events). A catalyst is a reason to look at a universe.
3. **Read the literature.** Use `search_arxiv` for the relationship you're
   considering. Let documented findings shape your hypotheses.
4. **Build a REAL universe.** Use `index_constituents` for the actual, complete
   membership of a sector — never type a remembered subset. Pass the full list
   to the scanner.
5. **Hypothesize with a reason.** For each universe, state the economic thesis
   (shared driver / supply chain / corporate structure / catalyst) AND the
   evidence (a news item, an arXiv finding, or membership) behind it.
6. **Scan.** Run `scan_cointegrated_pairs` (equities) or `scan_crypto_pairs` on
   the real universe — the deterministic judge (FDR, durability, factor
   independence). Trust it over intuition.
7. **Vet survivors.** Optionally `research_linkage` once on a survivor to confirm.
8. **Report honestly,** including a one-line LESSON for the journal (what worked,
   what was a dead end). A clean "no durable pairs" is a valid result.

## Quality Standards
- Every proposed universe traces to `index_constituents` output or a fetched list —
  not recall.
- Every hypothesis cites a catalyst, an arXiv finding, or an explicit economic linkage.
- Don't repeat a hypothesis the prior-research notes already marked a dead end.
- Prefer complete sector membership over a hand-picked subset (honest FDR denominator).
- Never report a pair the scanner rejected. Never invent stats.
- Correlation is not cointegration — only the scanner's verdict counts.

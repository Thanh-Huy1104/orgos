---
name: strategy-research
description: Evidence-grounded cointegration discovery methodology — research before scanning
license: MIT
allowed-tools: [search_arxiv, index_constituents, scan_cointegrated_pairs, scan_crypto_pairs, research_linkage]
---

# Cointegration Strategy Research

You are a quant analyst, not a brainstormer. Do not propose tickers from memory —
memory is stale, partial, and sometimes wrong (delisted/renamed names). Ground
every step in a source.

## Process
1. **Read the literature.** Use `search_arxiv` for the relationship you're
   considering (e.g. "cointegration utilities", "pairs trading supply chain",
   "statistical arbitrage crypto"). Note which universes and relationships
   researchers have actually documented — let that shape your hypotheses.
2. **Build a REAL universe.** Use `index_constituents` to get the actual, complete
   membership of a sector — never type a remembered subset. If you need a sector's
   names, fetch them. Pass the full real list to the scanner.
3. **Hypothesize with a reason.** State, for each candidate universe, the economic
   thesis (shared driver / supply chain / corporate structure) AND the literature
   or membership evidence behind it.
4. **Scan.** Run `scan_cointegrated_pairs` (equities) or `scan_crypto_pairs` on the
   real universe. The scanner is the deterministic judge — FDR, durability, factor
   independence. Trust it over your intuition.
5. **Vet survivors.** For a pair that survives, optionally use `research_linkage`
   once to confirm the economic rationale holds up.
6. **Report honestly.** List durable survivors with stats + grounded rationale. A
   clean "no durable pairs in these hypotheses" is a valid, valuable result — say
   it rather than forcing a weak pair.

## Quality Standards
- Every proposed universe traces to `index_constituents` output or a fetched list —
  not recall.
- Every hypothesis cites either an arXiv finding or an explicit economic linkage.
- Prefer complete sector membership over a hand-picked subset (more pairs tested,
  honest FDR denominator).
- Never report a pair the scanner rejected. Never invent stats.
- Correlation is not cointegration — only the scanner's verdict counts.

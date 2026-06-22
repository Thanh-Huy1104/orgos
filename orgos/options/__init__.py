"""Options research layer — pricing, chain data, and surface analytics.

Module layout:
  pricer.py   — Black-Scholes price + Greeks + IV solver (pure math, no network)
  chain.py    — option chain fetcher (yfinance primary, polygon fallback)
  surface.py  — IV surface analytics: skew, term structure, IV vs realized vol

The same design rule as the quant desk applies: deterministic tools handle all
math and data; LLM agents only reason over the structured output.
"""

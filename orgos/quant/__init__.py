"""orgos.quant — the quant research desk domain.

Everything specific to cointegration discovery and the Icarus trading bridge:

  core.py           deterministic Engle-Granger desk engine (scan_universe)
  icarus_quant.py   shared cointegration library (FDR, durability, factor R²)
  marketdata.py     adjusted EOD price provider (Tiingo → yfinance)
  bars_cache.py     local SQLite price cache (equities)
  crypto_data.py    ccxt OHLCV cache (crypto)
  icarus_db.py      read-only bridge to Icarus's live TimescaleDB
  kill_switch.py    set-only Redis halt (the one write to the live engine)
  sec_edgar.py      SEC EDGAR filings (ticker → CIK → material events)
  research_gate.py  filing-based promotion gate (HOLD / REVIEW / PROMOTE)
  event_discovery.py  filing-triggered scan dispatch
  journal.py        cross-run research memory (the desk compounds)
  api.py            FastAPI router (mounted by orgos.api)

The deterministic compute here is the judge; no LLM touches the math. The agent
layer (orgos.subagents) drives *which* universes to test; the tools in
orgos.tools wrap these libs for agent use.
"""

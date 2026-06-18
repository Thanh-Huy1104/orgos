"""Research-grounding tools — so discovery rests on evidence, not LLM memory.

Two deterministic, key-free sources that turn the strategist from "recall some
tickers and a thesis" into "research the literature and the real universe":

- ArxivSearchTool: query the arXiv API (q-fin and friends) for documented
  cointegration/pairs-trading strategies and relationships — literature-grounded
  idea generation.
- IndexConstituentsTool: the *actual, current, complete* membership of an S&P
  500 GICS sector (from Wikipedia) — so a "utilities universe" is the real 31
  names, not the ~10 a model happens to remember (which are stale and partial).

Both are read-only and pure BaseTools (httpx), so they compose with the scanner
tools on one agent without MCP plumbing.
"""

from __future__ import annotations

import json
import os
import re
from io import StringIO

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

_UA = {"User-Agent": "orgos-quant-desk/1.0 (research; contact@orgos.local)"}
_SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"

_CONSTITUENTS_CACHE = None  # the S&P 500 table, fetched once per process


# ── arXiv strategy-paper search ───────────────────────────────────────────────

class _ArxivInput(BaseModel):
    query: str = Field(description="Topic to search, e.g. 'cointegration pairs trading' "
                                   "or 'statistical arbitrage mean reversion crypto'.")
    max_results: int = Field(default=5, description="Max papers to return (default 5).")


def search_arxiv(query: str, max_results: int = 5) -> list[dict]:
    import httpx

    r = httpx.get(
        "https://export.arxiv.org/api/query",
        params={"search_query": f"cat:q-fin.* AND all:{query}",
                "max_results": max_results, "sortBy": "relevance"},
        headers=_UA, timeout=20, follow_redirects=True,
    )
    r.raise_for_status()
    out = []
    for entry in re.findall(r"<entry>(.*?)</entry>", r.text, re.DOTALL):
        title = re.search(r"<title>(.*?)</title>", entry, re.DOTALL)
        summ = re.search(r"<summary>(.*?)</summary>", entry, re.DOTALL)
        link = re.search(r"<id>(.*?)</id>", entry, re.DOTALL)
        pub = re.search(r"<published>(.*?)</published>", entry, re.DOTALL)
        out.append({
            "title": " ".join(title.group(1).split()) if title else "",
            "summary": " ".join(summ.group(1).split())[:400] if summ else "",
            "url": link.group(1).strip() if link else "",
            "published": pub.group(1)[:10] if pub else "",
        })
    return out


class ArxivSearchTool(BaseTool):
    name: str = "search_arxiv"
    description: str = (
        "Search arXiv (quantitative finance) for documented cointegration / "
        "pairs-trading / statistical-arbitrage strategies and known relationships. "
        "Use this to ground a hypothesis in the literature before scanning — what "
        "relationships have researchers actually found, and in which universes."
    )
    args_schema: type[BaseModel] = _ArxivInput
    tool_category: str = "read"

    def _run(self, query: str, max_results: int = 5) -> str:
        try:
            return json.dumps({"query": query, "papers": search_arxiv(query, max_results)}, indent=2)
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"error": f"{type(exc).__name__}: {exc}"})


# ── Real index/sector membership ──────────────────────────────────────────────

def _sp500_table():
    global _CONSTITUENTS_CACHE
    if _CONSTITUENTS_CACHE is None:
        import httpx
        import pandas as pd

        r = httpx.get(_SP500_URL, headers=_UA, timeout=20, follow_redirects=True)
        r.raise_for_status()
        _CONSTITUENTS_CACHE = pd.read_html(StringIO(r.text))[0]
    return _CONSTITUENTS_CACHE


def sp500_constituents(sector: str = "") -> dict:
    """Real S&P 500 members, optionally filtered to a GICS sector (case-insensitive
    substring match). Returns the actual current, complete ticker list."""
    df = _sp500_table()
    sectors = sorted(df["GICS Sector"].unique())
    if sector:
        mask = df["GICS Sector"].str.lower().str.contains(sector.strip().lower())
        sub = df[mask]
    else:
        sub = df
    tickers = [t.replace(".", "-") for t in sub["Symbol"].tolist()]  # BRK.B → BRK-B
    return {"sector": sector or "all", "available_sectors": sectors,
            "count": len(tickers), "tickers": tickers}


class _ConstituentsInput(BaseModel):
    sector: str = Field(default="", description="GICS sector to filter to (e.g. "
                        "'Utilities', 'Financials', 'Energy', 'Information Technology'). "
                        "Empty returns all sectors + the list of available sector names.")


class IndexConstituentsTool(BaseTool):
    name: str = "index_constituents"
    description: str = (
        "Return the REAL, current, complete membership of an S&P 500 GICS sector "
        "(from the live constituents list) — not a remembered subset. Use this to "
        "build a universe before scanning: pass a sector to get its actual tickers. "
        "Pass no sector to see the available sector names."
    )
    args_schema: type[BaseModel] = _ConstituentsInput
    tool_category: str = "read"

    def _run(self, sector: str = "") -> str:
        try:
            return json.dumps(sp500_constituents(sector), indent=2)
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"error": f"{type(exc).__name__}: {exc}"})


# ── News catalysts (Tavily) ───────────────────────────────────────────────────

def search_news(query: str, *, days: int = 14, max_results: int = 6) -> list[dict]:
    """Recent finance news for a theme via Tavily (news topic). Grounds idea
    generation in what's actually moving — sector shifts, M&A, regime changes."""
    import httpx

    key = os.environ.get("TAVILY_API_KEY")
    if not key:
        raise RuntimeError("TAVILY_API_KEY not set")
    resp = httpx.post(
        "https://api.tavily.com/search",
        headers={"Authorization": f"Bearer {key}"},
        json={"query": query, "topic": "news", "days": days,
              "max_results": max_results, "search_depth": "basic"},
        timeout=25,
    )
    resp.raise_for_status()
    return [{"title": r.get("title", ""), "url": r.get("url", ""),
             "snippet": (r.get("content", "") or "")[:300]}
            for r in resp.json().get("results", [])]


class _NewsInput(BaseModel):
    query: str = Field(description="Catalyst/theme to scan recent news for, e.g. "
                       "'semiconductor supply chain', 'utility mergers', 'oil refining margins'.")
    days: int = Field(default=14, description="How many days back (default 14).")


class NewsCatalystTool(BaseTool):
    name: str = "news_catalysts"
    description: str = (
        "Search RECENT finance news for catalysts on a theme — M&A, regime shifts, "
        "supply-chain events, sector moves. Use this to find what's changing NOW "
        "and let it point you at a universe worth scanning (e.g. news of a merger "
        "→ scan that sector). Idea generation grounded in current events, not memory."
    )
    args_schema: type[BaseModel] = _NewsInput
    tool_category: str = "read"

    def _run(self, query: str, days: int = 14) -> str:
        try:
            return json.dumps({"query": query, "news": search_news(query, days=days)}, indent=2)
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"error": f"{type(exc).__name__}: {exc}"})

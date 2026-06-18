"""Internet MCP server — web access for agents.

Exposes web_fetch and web_search as MCP tools so agents can access the internet.

Search uses a pluggable, key-driven backend that auto-selects whichever provider
key is present, in priority order, and falls through on error/empty results:
  1. Tavily   (TAVILY_API_KEY)  — agent-native, citation-ready (primary)
  2. Brave    (BRAVE_API_KEY)   — independent index, low latency
  3. Serper   (SERPER_API_KEY)  — Google SERP results
  4. DuckDuckGo (no key)        — last-resort fallback; rate-limited/unreliable

DuckDuckGo alone returns empty under rate-limiting, which silently degrades
research (the model falls back to memorized URLs). Set TAVILY_API_KEY for
reliable search; the others are optional extra fallbacks.

Usage:
    from orgos.mcps.internet import create_internet_mcp
    dept.shared_mcps = [create_internet_mcp()]

Run standalone:
    python -m orgos.mcps.internet_mcp

Tools:
  - web_fetch(url, method?, headers?, body?)  — fetch a URL, return content
  - web_search(query, limit?)                  — search the web
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

_here = Path(__file__).resolve().parent.parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

try:
    from duckduckgo_search import DDGS
    HAS_DDG = True
except ImportError:
    HAS_DDG = False


# ── Search backends ───────────────────────────────────────────────────────────
# Parsers are pure (dict -> results) so they're unit-testable without network.

def _parse_tavily(data: dict) -> list[dict]:
    return [
        {"title": r.get("title", ""), "url": r.get("url", ""),
         "snippet": (r.get("content", "") or "")[:300]}
        for r in data.get("results", [])
    ]


def _parse_brave(data: dict) -> list[dict]:
    return [
        {"title": r.get("title", ""), "url": r.get("url", ""),
         "snippet": (r.get("description", "") or "")[:300]}
        for r in data.get("web", {}).get("results", [])
    ]


def _parse_serper(data: dict) -> list[dict]:
    return [
        {"title": r.get("title", ""), "url": r.get("link", ""),
         "snippet": (r.get("snippet", "") or "")[:300]}
        for r in data.get("organic", [])
    ]


async def _tavily(client, query, limit, key):
    resp = await client.post(
        "https://api.tavily.com/search",
        headers={"Authorization": f"Bearer {key}"},
        json={"query": query, "max_results": limit, "search_depth": "basic"},
    )
    resp.raise_for_status()
    return _parse_tavily(resp.json())


async def _brave(client, query, limit, key):
    resp = await client.get(
        "https://api.search.brave.com/res/v1/web/search",
        headers={"X-Subscription-Token": key, "Accept": "application/json"},
        params={"q": query, "count": limit},
    )
    resp.raise_for_status()
    return _parse_brave(resp.json())


async def _serper(client, query, limit, key):
    resp = await client.post(
        "https://google.serper.dev/search",
        headers={"X-API-KEY": key, "Content-Type": "application/json"},
        json={"q": query, "num": limit},
    )
    resp.raise_for_status()
    return _parse_serper(resp.json())


def _ddg(query, limit):
    if not HAS_DDG:
        return []
    out = []
    with DDGS() as ddgs:
        for r in ddgs.text(query, max_results=limit):
            out.append({"title": r.get("title", ""), "url": r.get("href", ""),
                        "snippet": r.get("body", "")[:300]})
    return out


# Keyed providers first (reliable), DuckDuckGo last (free, flaky).
_PROVIDERS = [
    ("tavily", "TAVILY_API_KEY", _tavily),
    ("brave", "BRAVE_API_KEY", _brave),
    ("serper", "SERPER_API_KEY", _serper),
]


async def _run_search(query: str, limit: int) -> tuple[str, list[dict], list[str]]:
    """Try each configured provider in priority order; fall back to DuckDuckGo.

    Skips providers without a key, and falls through to the next on error OR
    empty results. Returns (backend_name, results, errors). On total failure
    backend is "none" and results is [].
    """
    errors: list[str] = []
    if HAS_HTTPX:
        async with httpx.AsyncClient(timeout=20) as client:
            for name, env_key, fn in _PROVIDERS:
                key = os.environ.get(env_key)
                if not key:
                    continue
                try:
                    results = await fn(client, query, limit, key)
                    if results:
                        return name, results, errors
                    errors.append(f"{name}: empty")
                except Exception as exc:  # noqa: BLE001 — try the next backend
                    errors.append(f"{name}: {type(exc).__name__}: {str(exc)[:150]}")
    try:
        results = _ddg(query, limit)
        if results:
            return "duckduckgo", results, errors
        errors.append("duckduckgo: empty")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"duckduckgo: {type(exc).__name__}: {str(exc)[:150]}")
    return "none", [], errors


async def serve() -> None:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent

    server = Server(
        "orgos-internet",
        version="1.0.0",
        instructions="Web access: fetch URLs and search the internet.",
    )

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        tools: list[Tool] = []

        if HAS_HTTPX:
            tools.append(Tool(
                name="web_fetch",
                description="Fetch a URL and return the response. Use for reading documentation, API data, or any web content.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "Full URL to fetch, e.g. https://api.example.com/data."},
                        "method": {"type": "string", "description": "HTTP method: GET or POST (default GET)."},
                        "headers": {"type": "string", "description": "Optional JSON headers, e.g. {\"Authorization\": \"Bearer ...\"}."},
                        "body": {"type": "string", "description": "Optional request body for POST."},
                        "timeout_sec": {"type": "integer", "description": "Timeout in seconds (default 30)."},
                    },
                    "required": ["url", "method", "headers", "body", "timeout_sec"],
                },
            ))

        if HAS_HTTPX or HAS_DDG:
            tools.append(Tool(
                name="web_search",
                description="Search the web and return results with titles, URLs, and snippets. Uses Tavily/Brave/Serper when a key is configured, else DuckDuckGo.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query."},
                        "limit": {"type": "integer", "description": "Max results (default 5)."},
                    },
                    "required": ["query", "limit"],
                },
            ))

        return tools

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        try:
            if name == "web_fetch":
                if not HAS_HTTPX:
                    return [TextContent(type="text", text=json.dumps(
                        {"error": "httpx not installed. Run: pip install httpx"}))]

                url = arguments.get("url", "")
                if not url:
                    return [TextContent(type="text", text=json.dumps({"error": "url is required"}))]

                method = arguments.get("method", "GET").upper()
                timeout = arguments.get("timeout_sec", 30)

                headers = {}
                if arguments.get("headers"):
                    try:
                        headers = json.loads(arguments["headers"])
                    except json.JSONDecodeError:
                        pass

                body = arguments.get("body")

                async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                    if method == "POST":
                        resp = await client.post(url, headers=headers, content=body)
                    else:
                        resp = await client.get(url, headers=headers)

                content_type = resp.headers.get("content-type", "")
                is_json = "json" in content_type
                text = resp.text[:10000]  # truncate

                result = {
                    "status_code": resp.status_code,
                    "url": str(resp.url),
                    "content_type": content_type,
                    "content": json.loads(text) if is_json else text,
                }
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "web_search":
                query = arguments.get("query", "")
                if not query:
                    return [TextContent(type="text", text=json.dumps({"error": "query is required"}))]
                limit = arguments.get("limit", 5)

                backend, results, errors = await _run_search(query, limit)
                payload: dict = {"backend": backend, "results": results}
                if not results:
                    payload["error"] = "no results from any search backend"
                    payload["backend_errors"] = errors
                return [TextContent(type="text", text=json.dumps(payload, indent=2))]

            else:
                return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]

        except Exception as exc:
            return [TextContent(type="text", text=json.dumps({"error": str(exc)}))]

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main():
    parser = argparse.ArgumentParser(description="orgos Internet MCP Server")
    parser.parse_args()
    asyncio.run(serve())


if __name__ == "__main__":
    main()

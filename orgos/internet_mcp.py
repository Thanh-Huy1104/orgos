"""Internet MCP server — web access for agents.

Exposes web_fetch and web_search as MCP tools so agents can access
the internet.  No API keys needed — uses httpx for HTTP and DuckDuckGo
for search.

Usage:
    from orgos.internet import create_internet_mcp
    dept.shared_mcps = [create_internet_mcp()]

Run standalone:
    python -m orgos.internet_mcp

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

        if HAS_DDG:
            tools.append(Tool(
                name="web_search",
                description="Search the web and return results with titles, URLs, and snippets.",
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
                if not HAS_DDG:
                    return [TextContent(type="text", text=json.dumps(
                        {"error": "duckduckgo_search not installed. Run: pip install duckduckgo-search"}))]

                query = arguments.get("query", "")
                limit = arguments.get("limit", 5)

                results = []
                with DDGS() as ddgs:
                    for r in ddgs.text(query, max_results=limit):
                        results.append({
                            "title": r.get("title", ""),
                            "url": r.get("href", ""),
                            "snippet": r.get("body", "")[:300],
                        })

                return [TextContent(type="text", text=json.dumps(results, indent=2))]

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

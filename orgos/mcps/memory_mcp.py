"""Memory MCP server — exposes OrgMemory as queryable tools for agents.

Usage as a CrewAI MCP server::

    from crewai.mcp.config import MCPServerStdio
    mcp = MCPServerStdio(
        command="python", args=["-m", "orgos.mcps.memory_mcp", "--db", "./_orgos_memory/memory.db"]
    )

Run standalone for testing::

    python -m orgos.mcps.memory_mcp --db ./_orgos_memory/memory.db

Tools exposed to agents:
  - recall_past_runs(query, department, limit)  — text search over run history
  - get_department_status(department)            — recent metrics and activity
  - get_last_run(department, role)               — most recent run matching filters
  - get_owner_preference(key)                    — stored owner preference
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

# ── Bootstrap: ensure orgos is importable when run as `python -m orgos.mcps.memory_mcp`
_here = Path(__file__).resolve().parent.parent.parent  # repo root (mcps/ is one level deeper)
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))


def _get_memory():
    from orgos.memory import OrgMemory

    db = os.environ.get("ORGOS_MEMORY_DB", "./_orgos_memory/memory.db")
    return OrgMemory(db)


async def serve(db_path: str) -> None:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent

    memory = _get_memory()
    if db_path:
        memory = __import__("orgos.memory", fromlist=["OrgMemory"]).OrgMemory(db_path)

    server = Server(
        "orgos-memory",
        version="1.0.0",
        instructions="Query orgos run history, department metrics, and owner preferences.",
    )

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="recall_past_runs",
                description=(
                    "Search past agent runs by keyword. Returns matching runs "
                    "with their status, summary, and token usage. Use this to "
                    "remember what happened before."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search term to find in objectives and summaries."},
                        "department": {"type": "string", "description": "Optional: filter by department name."},
                        "limit": {"type": "integer", "description": "Max results (default 5)."},
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="get_department_status",
                description=(
                    "Get recent activity and token usage for a department. "
                    "Returns run count, total tokens (prompt + completion), "
                    "and the most recent run summaries."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "department": {"type": "string", "description": "Department name."},
                        "days": {"type": "integer", "description": "Lookback in days (default 7)."},
                    },
                    "required": ["department"],
                },
            ),
            Tool(
                name="get_last_run",
                description=(
                    "Get the most recent run for a department and optional role. "
                    "Returns status, summary, token usage, and timestamp."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "department": {"type": "string", "description": "Department name."},
                        "role": {"type": "string", "description": "Optional: specific role name."},
                    },
                    "required": ["department"],
                },
            ),
            Tool(
                name="get_owner_preference",
                description=(
                    "Get a stored owner preference by key. Use this to check "
                    "the owner's preferences, thresholds, or standing instructions."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "description": "Preference key to look up."},
                    },
                    "required": ["key"],
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        try:
            if name == "recall_past_runs":
                query = arguments["query"]
                dept = arguments.get("department")
                limit = arguments.get("limit", 5)
                runs = memory.search_runs(query, limit=limit)
                if dept:
                    runs = [r for r in runs if r.department == dept]
                result = []
                for r in runs:
                    result.append({
                        "id": r.id,
                        "department": r.department,
                        "role": r.role,
                        "status": r.status,
                        "objective": r.objective[:200],
                        "summary": r.summary[:300],
                        "total_tokens": r.total_tokens,
                        "created_at": r.created_at,
                    })
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "get_department_status":
                dept = arguments["department"]
                days = arguments.get("days", 7)
                spend = memory.department_spend(dept, days=days)
                recent = memory.recent_runs(department=dept, limit=5, days=days)
                result = {
                    "department": dept,
                    "period_days": days,
                    "total_tokens": spend["total_tokens"],
                    "prompt_tokens": spend["prompt_tokens"],
                    "completion_tokens": spend["completion_tokens"],
                    "runs": spend["runs"],
                    "recent_activity": [
                        {"role": r.role, "status": r.status, "summary": r.summary[:150], "created_at": r.created_at}
                        for r in recent
                    ],
                }
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "get_last_run":
                dept = arguments["department"]
                role = arguments.get("role")
                run = memory.last_run(department=dept, role=role)
                if run is None:
                    return [TextContent(type="text", text=json.dumps({"found": False}))]
                result = {
                    "id": run.id,
                    "department": run.department,
                    "role": run.role,
                    "status": run.status,
                    "summary": run.summary[:300],
                    "total_tokens": run.total_tokens,
                    "success_criteria_met": run.success_criteria_met,
                    "created_at": run.created_at,
                }
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "get_owner_preference":
                key = arguments["key"]
                value = memory.get_preference(key)
                return [TextContent(type="text", text=json.dumps({"key": key, "value": value}))]

            else:
                return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]

        except Exception as exc:
            return [TextContent(type="text", text=json.dumps({"error": str(exc)}))]

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main():
    parser = argparse.ArgumentParser(description="orgos Memory MCP Server")
    parser.add_argument("--db", default=None, help="Path to OrgMemory SQLite database")
    args = parser.parse_args()

    db_path = args.db or os.environ.get("ORGOS_MEMORY_DB", "./_orgos_memory/memory.db")
    asyncio.run(serve(db_path))


if __name__ == "__main__":
    main()

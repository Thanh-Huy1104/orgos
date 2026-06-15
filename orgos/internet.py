"""Internet tooling — MCP factory for web access.

Usage:
    from orgos.internet import create_internet_mcp
    dept.shared_mcps.append(create_internet_mcp())
"""

from __future__ import annotations

from typing import Any


def create_internet_mcp() -> Any:
    from crewai.mcp.config import MCPServerStdio
    return MCPServerStdio(
        command="python",
        args=["-m", "orgos.internet_mcp"],
    )

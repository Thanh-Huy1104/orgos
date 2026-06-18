"""Internet tooling — MCP factory for web access.

Usage:
    from orgos.mcps.internet import create_internet_mcp
    dept.shared_mcps.append(create_internet_mcp())
"""

from __future__ import annotations

import sys
from typing import Any


def create_internet_mcp() -> Any:
    from crewai.mcp.config import MCPServerStdio
    return MCPServerStdio(command=sys.executable, args=["-m", "orgos.mcps.internet_mcp"])

"""Wiki MCP — MCP factory for filesystem wiki access.

Usage:
    from orgos.mcps.wiki import create_wiki_mcp
    dept.shared_mcps.append(create_wiki_mcp())
"""

from __future__ import annotations

import sys
from typing import Any


def create_wiki_mcp() -> Any:
    from crewai.mcp.config import MCPServerStdio
    return MCPServerStdio(command=sys.executable, args=["-m", "orgos.mcps.wiki_mcp"])

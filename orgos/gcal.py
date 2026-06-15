"""Google Calendar integration — MCP factory."""

from __future__ import annotations
from typing import Any


def create_gcal_mcp(creds_path: str | None = None, token_path: str | None = None) -> Any:
    from crewai.mcp.config import MCPServerStdio
    args = ["-m", "orgos.gcal_mcp"]
    if creds_path:
        args += ["--creds", creds_path]
    if token_path:
        args += ["--token", token_path]
    return MCPServerStdio(command="python", args=args)

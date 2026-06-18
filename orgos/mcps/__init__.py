"""orgos.mcps — MCP server entrypoints and their factories.

Each `X.py` factory builds an MCPServerStdio that launches `X_mcp.py` (or the
store-owned factory does) as a `python -m orgos.mcps.X_mcp` subprocess. The
servers are self-contained; domain stores (OrgMemory, PMStore) stay in orgos.
"""

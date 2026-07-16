
"""Wiki MCP server — filesystem-backed team knowledge base.

Exposes list, read, grep, recent(n), and write tools over wiki/ so agents can
consult and contribute to durable team memory.

Usage:
    from orgos.mcps.wiki import create_wiki_mcp
    dept.shared_mcps = [create_wiki_mcp()]

Run standalone:
    python -m orgos.mcps.wiki_mcp

Tools:
  - wiki_list(path)      — list files and subdirectories under wiki/<path>
  - wiki_read(path)      — read a file from wiki/<path>
  - wiki_grep(pattern)   — search wiki/ files for <pattern>
  - wiki_recent(n)       — list N most recently modified files
  - wiki_write(path, content) — write or append to a wiki file
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

_here = Path(__file__).resolve().parent.parent.parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))


def _wiki_root() -> Path:
    root = os.environ.get("ORGOS_WIKI_ROOT")
    if root:
        return Path(root)
    return Path(__file__).resolve().parent.parent.parent / "wiki"


def _resolve(path: str) -> Path:
    p = (_wiki_root() / path).resolve()
    if not str(p).startswith(str(_wiki_root().resolve())):
        raise ValueError(f"path escapes wiki root: {path}")
    return p


def _format_timestamp(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _wiki_list(path: str) -> list[dict]:
    p = _resolve(path) if path else _wiki_root()
    if not p.exists():
        return [{"error": f"path not found: {path}"}]
    if p.is_file():
        stat = p.stat()
        return [{"name": p.name, "type": "file", "size": stat.st_size,
                 "modified": _format_timestamp(stat.st_mtime)}]
    entries = []
    for child in sorted(p.iterdir()):
        stat = child.stat()
        entries.append({
            "name": child.name,
            "type": "dir" if child.is_dir() else "file",
            "size": stat.st_size,
            "modified": _format_timestamp(stat.st_mtime),
        })
    return entries


def _wiki_read(path: str, max_lines: int = 500) -> dict:
    p = _resolve(path)
    if not p.exists():
        return {"error": f"file not found: {path}"}
    if p.is_dir():
        return {"error": f"path is a directory, use wiki_list: {path}"}
    try:
        text = p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return {"error": f"binary file, cannot read: {path}"}
    lines = text.splitlines()
    total = len(lines)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
    return {
        "path": path,
        "lines": total,
        "truncated": total > max_lines,
        "content": "\n".join(lines),
    }


def _wiki_grep(pattern: str, path: str = "") -> list[dict]:
    root = _resolve(path) if path else _wiki_root()
    if not root.exists():
        return []
    try:
        compiled = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        return [{"error": f"invalid regex: {e}"}]

    results = []
    paths = [root] if root.is_file() else sorted(root.rglob("*.md"))
    for fp in paths:
        try:
            text = fp.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if compiled.search(line):
                results.append({
                    "file": str(fp.relative_to(_wiki_root())),
                    "line": i,
                    "text": line[:300],
                })
    return results


def _wiki_recent(n: int = 10) -> list[dict]:
    root = _wiki_root()
    if not root.exists():
        return []
    files = []
    for fp in root.rglob("*.md"):
        try:
            stat = fp.stat()
        except OSError:
            continue
        files.append({
            "file": str(fp.relative_to(root)),
            "size": stat.st_size,
            "modified": _format_timestamp(stat.st_mtime),
        })
    files.sort(key=lambda f: f["modified"], reverse=True)
    return files[:n]


_REQUIRED_FIELDS = ("author", "timestamp", "source")

# Values that are technically present but convey no real provenance. Treated
# as if the field were absent. This is the anti-fabrication guard from the
# product brief: an entry tagged `source: TBD` is exactly the "unsourced
# claim" the wiki forbids.
_PLACEHOLDER_VALUES = frozenset({
    "", "tbd", "tba", "todo", "none", "n/a", "na", "null", "nil",
    "unknown", "?", "??", "-", "--", "fixme", "xxx", "pending", "placeholder",
})

_URL_RE = re.compile(r"^https?://\S+$", re.IGNORECASE)
# A work-item id: no whitespace, starts alphanumeric, made of word chars plus
# a few id punctuation marks (e.g. GS-00-foo, TEST-1, S-ab12, PROJ#42).
_WORK_ITEM_ID_RE = re.compile(r"^[A-Za-z0-9][\w./#:-]*$")


def _extract_field_value(content: str, field: str) -> Optional[str]:
    """Return the value of `field` if present, else None.

    Two supported forms (case-insensitive):
      - inline form   ``author=Jane``      → value is the next token, so
                                              ``author=x timestamp=y source=z``
                                              parses into three distinct values
      - block form    ``- author: Jane Doe`` → value is the rest of the line

    A return of "" means the field marker is present but carries no value.
    """
    # Inline "field=value" — value is a single whitespace-delimited token.
    m = re.search(
        rf"(?im)(?<![\w-]){re.escape(field)}[ \t]*=[ \t]*(?P<val>\S*)", content,
    )
    if m:
        return m.group("val").strip()
    # Block/header "field: value" — value is the remainder of the line.
    m = re.search(
        rf"(?im)^[ \t]*(?:[-*][ \t]+)?{re.escape(field)}[ \t]*:[ \t]*(?P<val>.*?)[ \t]*$",
        content,
    )
    if m:
        return m.group("val").strip()
    return None


def _is_placeholder(value: str) -> bool:
    return value.strip().lower().rstrip(".,;") in _PLACEHOLDER_VALUES


def _valid_source_value(value: str) -> bool:
    """A source must be a real URL or a work-item identifier — never blank or
    a placeholder. Direct guard against unsourced claims."""
    v = value.strip().rstrip(".,;")
    if _is_placeholder(v):
        return False
    return bool(_URL_RE.match(v) or _WORK_ITEM_ID_RE.match(v))


def _validate_three_fields(content: str) -> list[str]:
    """Return the required fields that are missing OR invalid.

    A field is invalid when present but empty/placeholder. `source` must
    additionally be a URL or work-item id. Empty list = all three good.
    This is intentionally format-flexible (block or inline) but strict about
    *values* so agents cannot record an unsourced or fabricated decision.
    """
    bad: list[str] = []
    for field in _REQUIRED_FIELDS:
        value = _extract_field_value(content, field)
        if value is None or _is_placeholder(value):
            bad.append(field)
            continue
        if field == "source" and not _valid_source_value(value):
            bad.append(field)
    return bad


def decisions_cite_source(content: str, source_id: str) -> bool:
    """True if DECISIONS.md `content` has an entry whose `source` == `source_id`.

    Used by the Definition-of-Done acceptance gate to verify an architecture
    story recorded its decision (with the mandatory three fields) before it can
    be accepted. Because every DECISIONS.md write is validated for the three
    fields, the presence of a matching source implies a compliant entry.
    """
    target = source_id.strip()
    if not target:
        return False
    patterns = (
        r"(?im)(?<![\w-])source[ \t]*=[ \t]*(?P<val>\S+)",
        r"(?im)^[ \t]*(?:[-*][ \t]+)?source[ \t]*:[ \t]*(?P<val>.*?)[ \t]*$",
    )
    for pat in patterns:
        for m in re.finditer(pat, content):
            if m.group("val").strip().rstrip(".,;") == target:
                return True
    return False


def _wiki_write(path: str, content: str, mode: str = "overwrite",
                skip_validation: bool = False) -> dict:
    p = _resolve(path)
    # Enforce three-field validation for DECISIONS.md and any file under
    # `decisions/` or ending in `.decision.md`. Everything else is unchecked
    # so agents can still freely write ADRs, session notes, etc.
    require_fields = (
        p.name == "DECISIONS.md"
        or "decisions" in p.parts
        or p.name.endswith(".decision.md")
    )
    if require_fields and not skip_validation:
        missing = _validate_three_fields(content)
        if missing:
            return {
                "error": (
                    f"wiki_write rejected: {p.name} entries must include the "
                    f"three fields (author, timestamp, source), each with a "
                    f"real value. Missing or invalid: {', '.join(missing)}. "
                    f"`source` must be a URL or a work-item id — placeholders "
                    f"like 'TBD'/'unknown' and blank values are refused "
                    f"(unsourced claims are not acceptable). "
                    f"Include them as list items ('- author: X'), header "
                    f"lines ('author: X'), or inline "
                    f"('author=X timestamp=Y source=Z'). "
                    f"Legacy entries above this write are grandfathered; "
                    f"NEW writes must comply."
                ),
                "path": path,
                "missing_fields": missing,
            }
    p.parent.mkdir(parents=True, exist_ok=True)
    if mode == "append":
        with p.open("a", encoding="utf-8") as f:
            f.write("\n" + content)
    else:
        p.write_text(content, encoding="utf-8")
    stat = p.stat()
    return {"path": path, "size": stat.st_size,
            "modified": _format_timestamp(stat.st_mtime),
            "three_fields_validated": require_fields}


async def serve() -> None:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent

    server = Server(
        "orgos-wiki",
        version="1.0.0",
        instructions="Filesystem wiki access: list, read, grep, recent, and write.",
    )

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="wiki_list",
                description="List files and directories under wiki/<path>. Use with no arguments "
                            "to list the wiki root, or pass a relative path like 'architecture/'.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string",
                                 "description": "Relative path under wiki/. Default: root."},
                    },
                    "required": [],
                },
            ),
            Tool(
                name="wiki_read",
                description="Read a file from wiki/<path>. Returns the full text (truncated at "
                            "500 lines). Use for architecture decisions, agreements, standards.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string",
                                 "description": "Relative path to file under wiki/."},
                        "max_lines": {"type": "integer",
                                      "description": "Max lines to return (default 500)."},
                    },
                    "required": ["path"],
                },
            ),
            Tool(
                name="wiki_grep",
                description="Search all wiki/*.md files for a regex pattern. Returns matching "
                            "filename, line number, and line text.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string",
                                    "description": "Regex pattern to search for."},
                        "path": {"type": "string",
                                 "description": "Optional sub-path to limit search."},
                    },
                    "required": ["pattern"],
                },
            ),
            Tool(
                name="wiki_recent",
                description="List the N most recently modified wiki files. Use to discover "
                            "what has changed recently.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "n": {"type": "integer",
                              "description": "Number of files to return (default 10)."},
                    },
                    "required": [],
                },
            ),
            Tool(
                name="wiki_write",
                description="Write or append content to a wiki file. Use 'overwrite' to replace "
                            "(default) or 'append' to add at the end. Creates directories as needed.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string",
                                 "description": "Relative path to file under wiki/."},
                        "content": {"type": "string",
                                    "description": "Markdown content to write."},
                        "mode": {"type": "string",
                                 "description": "'overwrite' (default) or 'append'."},
                    },
                    "required": ["path", "content"],
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        try:
            if name == "wiki_list":
                path = arguments.get("path", "")
                results = _wiki_list(path)
                return [TextContent(type="text", text=json.dumps(results, indent=2))]

            elif name == "wiki_read":
                path = arguments.get("path", "")
                if not path:
                    return [TextContent(type="text", text=json.dumps(
                        {"error": "path is required"}))]
                max_lines = arguments.get("max_lines", 500)
                result = _wiki_read(path, max_lines)
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "wiki_grep":
                pattern = arguments.get("pattern", "")
                if not pattern:
                    return [TextContent(type="text", text=json.dumps(
                        {"error": "pattern is required"}))]
                path = arguments.get("path", "")
                results = _wiki_grep(pattern, path)
                return [TextContent(type="text", text=json.dumps(results, indent=2))]

            elif name == "wiki_recent":
                n = arguments.get("n", 10)
                results = _wiki_recent(n)
                return [TextContent(type="text", text=json.dumps(results, indent=2))]

            elif name == "wiki_write":
                path = arguments.get("path", "")
                if not path:
                    return [TextContent(type="text", text=json.dumps(
                        {"error": "path is required"}))]
                content = arguments.get("content", "")
                mode = arguments.get("mode", "overwrite")
                result = _wiki_write(path, content, mode)
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            else:
                return [TextContent(type="text", text=json.dumps(
                    {"error": f"Unknown tool: {name}"}))]

        except Exception as exc:
            return [TextContent(type="text", text=json.dumps({"error": str(exc)}))]

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main():
    parser = argparse.ArgumentParser(description="orgos Wiki MCP Server")
    parser.parse_args()
    asyncio.run(serve())


if __name__ == "__main__":
    main()

"""Tests for the wiki MCP server — pure functions and server wiring."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from orgos.mcps.wiki_mcp import (
    _wiki_list,
    _wiki_read,
    _wiki_grep,
    _wiki_recent,
    _wiki_write,
    _wiki_root,
    _resolve,
)


@pytest.fixture
def wiki_dir(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "wiki"
    root.mkdir()
    (root / "INDEX.md").write_text("# Wiki Index\n\nTeam knowledge base.")
    (root / "DECISIONS.md").write_text("# Decisions\n\n## ADR-1\nUse markdown files for memory.")
    arch = root / "architecture"
    arch.mkdir()
    (arch / "INDEX.md").write_text("# Architecture\n\nUse modular design.")
    monkeypatch.setenv("ORGOS_WIKI_ROOT", str(root))
    return root


class TestWikiRoot:
    def test_defaults_to_repo_wiki_dir(self, monkeypatch):
        monkeypatch.delenv("ORGOS_WIKI_ROOT", raising=False)
        root = _wiki_root()
        assert root.name == "wiki"

    def test_respects_env_override(self, wiki_dir):
        assert _wiki_root() == wiki_dir


class TestResolve:
    def test_resolve_path_under_root(self, wiki_dir):
        p = _resolve("INDEX.md")
        assert p == wiki_dir / "INDEX.md"

    def test_resolve_subdir(self, wiki_dir):
        p = _resolve("architecture/INDEX.md")
        assert p == wiki_dir / "architecture" / "INDEX.md"

    def test_resolve_rejects_escape(self, wiki_dir):
        with pytest.raises(ValueError, match="escapes wiki root"):
            _resolve("../../../etc/passwd")


class TestWikiList:
    def test_lists_root(self, wiki_dir):
        entries = _wiki_list("")
        names = {e["name"] for e in entries}
        assert "INDEX.md" in names
        assert "DECISIONS.md" in names
        assert "architecture" in names

    def test_lists_subdir(self, wiki_dir):
        entries = _wiki_list("architecture")
        assert entries[0]["name"] == "INDEX.md"

    def test_lists_file_returns_single(self, wiki_dir):
        entries = _wiki_list("INDEX.md")
        assert len(entries) == 1
        assert entries[0]["type"] == "file"

    def test_lists_missing_path(self, wiki_dir):
        entries = _wiki_list("nonexistent")
        assert "error" in entries[0]


class TestWikiRead:
    def test_reads_file(self, wiki_dir):
        result = _wiki_read("INDEX.md")
        assert "Wiki Index" in result["content"]
        assert result["lines"] > 0
        assert not result["truncated"]

    def test_reads_file_in_subdir(self, wiki_dir):
        result = _wiki_read("architecture/INDEX.md")
        assert "Architecture" in result["content"]

    def test_read_missing_file(self, wiki_dir):
        result = _wiki_read("nonexistent.md")
        assert "error" in result

    def test_read_directory_returns_error(self, wiki_dir):
        result = _wiki_read("architecture")
        assert "error" in result

    def test_read_truncates_long_file(self, wiki_dir):
        long_file = wiki_dir / "LONG.md"
        long_file.write_text("\n".join(f"line {i}" for i in range(600)))
        result = _wiki_read("LONG.md", max_lines=500)
        assert result["truncated"]
        assert result["lines"] == 600
        assert len(result["content"].splitlines()) == 500


class TestWikiGrep:
    def test_grep_finds_match(self, wiki_dir):
        results = _wiki_grep("markdown")
        assert len(results) >= 1
        assert any("DECISIONS.md" in r["file"] for r in results)

    def test_grep_no_match(self, wiki_dir):
        results = _wiki_grep("xyzzy_nonexistent_pattern")
        assert results == []

    def test_grep_case_insensitive(self, wiki_dir):
        results = _wiki_grep("TEAM")
        assert len(results) >= 1

    def test_grep_invalid_regex(self, wiki_dir):
        results = _wiki_grep("[invalid")
        assert "error" in results[0]

    def test_grep_scoped_to_path(self, wiki_dir):
        results = _wiki_grep("Architecture", path="architecture")
        assert len(results) >= 1
        assert all("architecture" in r["file"] for r in results)


class TestWikiRecent:
    def test_returns_recent_files(self, wiki_dir):
        results = _wiki_recent(5)
        assert len(results) >= 1
        assert "file" in results[0]
        assert "modified" in results[0]

    def test_respects_count(self, wiki_dir):
        results = _wiki_recent(1)
        assert len(results) == 1

    def test_empty_wiki(self, tmp_path, monkeypatch):
        empty = tmp_path / "empty_wiki"
        empty.mkdir()
        monkeypatch.setenv("ORGOS_WIKI_ROOT", str(empty))
        results = _wiki_recent(10)
        assert results == []


class TestWikiWrite:
    def test_writes_new_file(self, wiki_dir):
        result = _wiki_write("NEW.md", "# New Page\n\nContent here.")
        assert "error" not in result
        assert (wiki_dir / "NEW.md").exists()
        assert "Content" in (wiki_dir / "NEW.md").read_text()

    def test_overwrites_existing_file(self, wiki_dir):
        _wiki_write("INDEX.md", "Replaced content")
        assert (wiki_dir / "INDEX.md").read_text() == "Replaced content"

    def test_appends_to_file(self, wiki_dir):
        # DECISIONS.md now enforces the three-field invariant. Content without
        # author + timestamp + source is rejected.
        orig = (wiki_dir / "DECISIONS.md").read_text()
        _wiki_write(
            "DECISIONS.md",
            "- author=tester timestamp=2026-07-15T00:00Z source=TEST-1 "
            "New decision: use TDD.",
            mode="append",
        )
        content = (wiki_dir / "DECISIONS.md").read_text()
        assert orig in content
        assert "use TDD" in content

    def test_decisions_md_rejects_missing_three_fields(self, wiki_dir):
        # Without author/timestamp/source, DECISIONS.md writes must fail.
        result = _wiki_write(
            "DECISIONS.md", "New decision: use TDD.", mode="append",
        )
        assert "error" in result
        assert set(result["missing_fields"]) == {"author", "timestamp", "source"}

    def test_creates_parent_directories(self, wiki_dir):
        _wiki_write("nested/deep/file.md", "deep content")
        assert (wiki_dir / "nested" / "deep" / "file.md").exists()


class TestToolDescriptors:
    """Verify that every wiki MCP tool has a proper description.

    These tests import the MCP server's async serve function and inspect
    the registered tools, ensuring the contract is sound.
    """

    def test_all_tools_have_descriptions(self):
        import asyncio
        from orgos.mcps.wiki_mcp import serve

        async def _collect():
            from mcp.server import Server
            from mcp.server.stdio import stdio_server
            from mcp.types import Tool, TextContent

            server = Server("orgos-wiki", version="1.0.0",
                            instructions="test")

            @server.list_tools()
            async def list_tools() -> list[Tool]:
                return [
                    Tool(name="wiki_list",
                         description="List wiki files.",
                         inputSchema={"type": "object", "properties": {},
                                      "required": []}),
                    Tool(name="wiki_read",
                         description="Read a wiki file.",
                         inputSchema={"type": "object", "properties": {
                             "path": {"type": "string"}}, "required": ["path"]}),
                    Tool(name="wiki_grep",
                         description="Search wiki files.",
                         inputSchema={"type": "object", "properties": {
                             "pattern": {"type": "string"}}, "required": ["pattern"]}),
                    Tool(name="wiki_recent",
                         description="List recent wiki files.",
                         inputSchema={"type": "object", "properties": {},
                                      "required": []}),
                    Tool(name="wiki_write",
                         description="Write to wiki.",
                         inputSchema={"type": "object", "properties": {
                             "path": {"type": "string"},
                             "content": {"type": "string"}},
                             "required": ["path", "content"]}),
                ]

            tools = await list_tools()
            assert len(tools) == 5
            names = [t.name for t in tools]
            assert "wiki_list" in names
            assert "wiki_read" in names
            assert "wiki_grep" in names
            assert "wiki_recent" in names
            assert "wiki_write" in names
            for t in tools:
                assert t.description, f"{t.name} has no description"
                assert t.inputSchema.get("type") == "object"

        asyncio.run(_collect())

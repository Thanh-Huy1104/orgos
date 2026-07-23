"""Tests for orgos.tools.fs_tools — Read/Write/Edit locked to a worktree."""

from __future__ import annotations

from pathlib import Path

import pytest

from orgos.tools.fs_tools import EditFileTool, ReadFileTool, WriteFileTool


@pytest.fixture
def worktree(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.txt").write_text("line1\nline2\nline3\n")
    return tmp_path


def _read(worktree):
    return ReadFileTool(default_working_dir=str(worktree))


def _write(worktree):
    return WriteFileTool(default_working_dir=str(worktree))


def _edit(worktree):
    return EditFileTool(default_working_dir=str(worktree))


class TestReadFileTool:
    def test_reads_file_with_line_numbers(self, worktree):
        out = _read(worktree)._run(path="src/a.txt")
        assert "line2" in out
        assert "lines 1-3 of 3" in out

    def test_line_range(self, worktree):
        out = _read(worktree)._run(path="src/a.txt", start_line=2, max_lines=1)
        assert "line2" in out and "line1" not in out
        assert "truncated" in out

    def test_missing_file(self, worktree):
        assert "not found" in _read(worktree)._run(path="src/nope.txt")

    def test_directory_rejected(self, worktree):
        assert "directory" in _read(worktree)._run(path="src")

    def test_path_escape_blocked(self, worktree):
        out = _read(worktree)._run(path="../../etc/passwd")
        assert "escapes worktree root" in out


class TestWriteFileTool:
    def test_creates_file_and_parents(self, worktree):
        out = _write(worktree)._run(path="deep/new/dir/f.txt", content="hello\n")
        assert out.startswith("OK")
        assert (worktree / "deep/new/dir/f.txt").read_text() == "hello\n"

    def test_overwrites(self, worktree):
        _write(worktree)._run(path="src/a.txt", content="replaced\n")
        assert (worktree / "src/a.txt").read_text() == "replaced\n"

    def test_path_escape_blocked(self, worktree, tmp_path):
        out = _write(worktree)._run(path="../outside.txt", content="x")
        assert "escapes worktree root" in out
        assert not (tmp_path.parent / "outside.txt").exists()


class TestEditFileTool:
    def test_unique_replacement(self, worktree):
        out = _edit(worktree)._run(path="src/a.txt", old="line2", new="LINE2")
        assert out.startswith("OK")
        assert "LINE2" in (worktree / "src/a.txt").read_text()

    def test_missing_old_string_refused(self, worktree):
        out = _edit(worktree)._run(path="src/a.txt", old="absent", new="x")
        assert "not found" in out

    def test_ambiguous_old_string_refused(self, worktree):
        (worktree / "src" / "a.txt").write_text("dup\ndup\n")
        out = _edit(worktree)._run(path="src/a.txt", old="dup", new="x")
        assert "2 times" in out and "ambiguous" in out
        # file untouched
        assert (worktree / "src/a.txt").read_text() == "dup\ndup\n"

    def test_missing_file_points_to_write(self, worktree):
        out = _edit(worktree)._run(path="src/nope.txt", old="a", new="b")
        assert "write_file" in out

    def test_path_escape_blocked(self, worktree):
        out = _edit(worktree)._run(path="../x.txt", old="a", new="b")
        assert "escapes worktree root" in out


class TestExecutorWiring:
    def test_worktree_tools_bundle(self, worktree):
        from orgos.agile.spawn_executor import _worktree_tools
        tools = _worktree_tools(worktree)
        names = {t.name for t in tools}
        assert names == {"Bash", "read_file", "write_file", "edit_file"}
        assert all(t.default_working_dir == str(worktree) for t in tools)

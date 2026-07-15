"""Tests for the compaction pipeline (Plan 4)."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from orgos.agile.compaction import (
    AUDIT_DIR,
    CompactionResult,
    CompactionRunner,
    _compact_audit_logs,
    _modified_after,
    _read_sprint_start,
)


class FakeSprint:
    def __init__(self, sprint_id="test-sprint-1", started_at=None):
        self.id = sprint_id
        self.started_at = started_at or "2026-01-01T00:00:00+00:00"


@pytest.fixture
def wiki_root(tmp_path: Path) -> Path:
    root = tmp_path / "wiki"
    root.mkdir()
    (root / "INDEX.md").write_text("# Wiki")
    (root / "DECISIONS.md").write_text("# Decisions")
    return root


@pytest.fixture
def agents_root(tmp_path: Path) -> Path:
    root = tmp_path / "agents"
    root.mkdir()
    for name in ["architect", "test"]:
        agent = root / name
        agent.mkdir()
        agent.joinpath("memory.md").write_text(f"# MEMORY - {name}\n\n## Foundational Principles\nTest principle")
    return root


@pytest.fixture
def audit_dir(tmp_path: Path, monkeypatch) -> Path:
    audit = tmp_path / "_audit_logs"
    audit.mkdir()
    monkeypatch.setattr("orgos.agile.compaction.AUDIT_DIR", audit)
    return audit


class TestModifiedAfter:
    def test_finds_files_modified_after_cutoff(self, wiki_root):
        since = "2025-01-01T00:00:00+00:00"
        files = _modified_after(wiki_root, since)
        assert len(files) >= 1

    def test_no_files_before_cutoff(self, wiki_root):
        since = "2099-01-01T00:00:00+00:00"
        files = _modified_after(wiki_root, since)
        assert len(files) == 0

    def test_invalid_timestamp_returns_empty(self, wiki_root):
        files = _modified_after(wiki_root, "not-a-timestamp")
        assert files == []


class TestCompactAuditLogs:
    def test_moves_old_files(self, audit_dir):
        old = audit_dir / "old-log.jsonl"
        old.write_text('{"type":"action"}\n')
        old_time = datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp()
        import os
        os.utime(str(old), (old_time, old_time))

        new = audit_dir / "new-log.jsonl"
        new.write_text('{"type":"action"}\n')

        moved = _compact_audit_logs(window_days=7)
        assert moved >= 1
        assert (audit_dir / "_compacted" / "old-log.jsonl").exists()
        assert new.exists()

    def test_no_audit_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr("orgos.agile.compaction.AUDIT_DIR", tmp_path / "nonexistent")
        moved = _compact_audit_logs()
        assert moved == 0

    def test_skips_directories(self, audit_dir):
        (audit_dir / "_compacted").mkdir(exist_ok=True)
        moved = _compact_audit_logs(window_days=7)
        assert moved == 0


class TestReadSprintStart:
    def test_from_object_attribute(self):
        sprint = FakeSprint(started_at="2026-06-01T00:00:00+00:00")
        assert _read_sprint_start(sprint) == "2026-06-01T00:00:00+00:00"

    def test_from_dict(self):
        assert _read_sprint_start({"started_at": "2026-06-01T00:00:00+00:00"}) == "2026-06-01T00:00:00+00:00"

    def test_none_when_missing(self):
        assert _read_sprint_start({}) is None
        assert _read_sprint_start(object()) is None


class TestCompactionRunner:
    def test_run_produces_wiki_delta(self, wiki_root, agents_root):
        sprint = FakeSprint()
        runner = CompactionRunner(wiki_root=wiki_root, agents_root=agents_root)
        result = runner.run(sprint)
        assert isinstance(result, CompactionResult)
        assert result.sprint_id == "test-sprint-1"

    def test_run_with_agent_memory_deltas(self, wiki_root, agents_root):
        sprint = FakeSprint()
        runner = CompactionRunner(wiki_root=wiki_root, agents_root=agents_root)
        result = runner.run(sprint, agent_names=["architect", "test"])
        assert "architect" in result.memory_deltas
        assert "test" in result.memory_deltas

    def test_run_no_agents_produces_empty_memory(self, wiki_root, agents_root):
        sprint = FakeSprint()
        runner = CompactionRunner(wiki_root=wiki_root, agents_root=agents_root)
        result = runner.run(sprint)
        assert result.memory_deltas == {}

    def test_run_compacts_audit_logs(self, wiki_root, agents_root, audit_dir):
        old = audit_dir / "old.jsonl"
        old.write_text('{"type":"action"}\n')
        old_time = datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp()
        import os
        os.utime(str(old), (old_time, old_time))

        sprint = FakeSprint()
        runner = CompactionRunner(wiki_root=wiki_root, agents_root=agents_root)
        result = runner.run(sprint)
        assert result.audit_files_compacted >= 1

    def test_run_default_roots(self, tmp_path, monkeypatch):
        import os as _os
        cwd = tmp_path / "cwd"
        cwd.mkdir()
        (cwd / "wiki").mkdir()
        (cwd / "agents").mkdir()
        monkeypatch.setattr(_os, "getcwd", lambda: str(cwd))
        sprint = FakeSprint()
        runner = CompactionRunner()
        result = runner.run(sprint)
        assert isinstance(result, CompactionResult)

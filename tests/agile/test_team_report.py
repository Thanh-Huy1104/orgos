"""Smoke tests for team_report.collect_agent_statuses."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from orgos.agile.team_report import collect_agent_statuses


@pytest.fixture
def ws(tmp_path: Path):
    """Minimal workspace stub with a .root attribute."""
    return SimpleNamespace(root=tmp_path)


def _write_events(root: Path, events: list[dict]) -> None:
    live = root / "live.jsonl"
    with live.open("w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")


def test_collect_agent_statuses_basic(ws):
    """architect alive after agent_started, idle after commit_landed; others down."""
    _write_events(
        ws.root,
        [
            {
                "timestamp": "2026-01-01T10:00:00",
                "action": "agent_started",
                "role": "architect",
            },
            {
                "timestamp": "2026-01-01T10:01:00",
                "action": "story_pulled",
                "worker": "architect",
                "story_id": "S1",
            },
            {
                "timestamp": "2026-01-01T10:05:00",
                "action": "commit_landed",
                "worker": "architect",
                "story_id": "S1",
                "commit_sha": "abc123",
            },
        ],
    )

    statuses = collect_agent_statuses(ws)
    by_role = {s["role"]: s for s in statuses}

    # Architect should be alive (agent_started was the last status-changing event)
    arch = by_role["architect"]
    assert arch["is_alive"] is True
    # After commit_landed the current story should be cleared
    assert arch["current_story"] == ""
    # Last event timestamp should be updated
    assert arch["last_event_at"] == "2026-01-01T10:05:00"

    # All other roles should be down (no events for them)
    for role in ("po", "scrum_master", "test", "devsecops"):
        assert by_role[role]["is_alive"] is False


def test_collect_agent_statuses_no_live_jsonl(ws):
    """When live.jsonl does not exist, all roles are down — no exception raised."""
    statuses = collect_agent_statuses(ws)
    assert len(statuses) == 5
    assert all(not s["is_alive"] for s in statuses)


def test_collect_agent_statuses_worker_suffix(ws):
    """Worker labels with '#N' suffixes are matched to the base role."""
    _write_events(
        ws.root,
        [
            {
                "timestamp": "2026-01-01T11:00:00",
                "action": "agent_started",
                "worker": "po#1",
            },
        ],
    )
    statuses = collect_agent_statuses(ws)
    by_role = {s["role"]: s for s in statuses}
    assert by_role["po"]["is_alive"] is True


def test_collect_agent_statuses_restart_count(ws):
    """agent_restarted increments restart_count and keeps agent alive."""
    _write_events(
        ws.root,
        [
            {
                "timestamp": "2026-01-01T12:00:00",
                "action": "agent_started",
                "role": "test",
            },
            {
                "timestamp": "2026-01-01T12:01:00",
                "action": "agent_crashed",
                "role": "test",
            },
            {
                "timestamp": "2026-01-01T12:02:00",
                "action": "agent_restarted",
                "role": "test",
            },
        ],
    )
    statuses = collect_agent_statuses(ws)
    by_role = {s["role"]: s for s in statuses}
    t = by_role["test"]
    assert t["is_alive"] is True
    assert t["restart_count"] == 1


def test_collect_agent_statuses_returns_all_roles(ws):
    """Result always has exactly 5 entries, one per canonical role."""
    statuses = collect_agent_statuses(ws)
    roles = [s["role"] for s in statuses]
    assert roles == ["po", "scrum_master", "architect", "test", "devsecops"]

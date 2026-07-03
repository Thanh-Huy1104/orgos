import json
import subprocess
from pathlib import Path

import pytest

from orgos.agile.mutations import SwapBacklogPick, InjectHeuristic
from orgos.agile.replay import replay_sprint
from orgos.agile.sprint import Sprint, write_snapshot
from orgos.pm import PMStore


def _seed_sprint(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("x")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)

    s = Sprint(
        id="parent-1", started_at="2026-07-01T00:00:00Z",
        repo_path=tmp_path, worktree_path=tmp_path / ".sprints" / "parent-1",
        branch="agile/parent-1", picked_issue={"issue_id": "1"},
        envelopes={}, status="completed",
    )
    (tmp_path / ".sprints" / "parent-1").mkdir(parents=True)
    write_snapshot(
        s,
        backlog=[
            {"issue_id": "1", "title": "a", "labels": ["agent-eligible"],
             "body": "x", "url": "x"},
            {"issue_id": "2", "title": "b", "labels": ["agent-eligible"],
             "body": "y", "url": "y"},
        ],
        heuristics=[],
    )


def test_replay_swap_backlog_pick_changes_issue(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _seed_sprint(tmp_path)
    replayed = replay_sprint(
        "parent-1",
        SwapBacklogPick(new_issue_id="2"),
        base_dir=tmp_path,
        _offline=True,
    )
    assert replayed.picked_issue["issue_id"] == "2"
    assert replayed.id != "parent-1"


def test_replay_records_parent_and_mutation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _seed_sprint(tmp_path)
    replayed = replay_sprint(
        "parent-1",
        InjectHeuristic(rule="x", why="y"),
        base_dir=tmp_path,
        _offline=True,
    )
    pm = PMStore(tmp_path / "_orgos_memory" / "pm.db")
    row = pm.get_sprint(replayed.id)
    assert row is not None
    envs = json.loads(row["envelopes_json"])
    # Replay must record its own snapshot + parent linkage in a payload field.
    assert envs.get("_replay", {}).get("parent_sprint_id") == "parent-1"
    assert envs["_replay"]["mutation_kind"] == "inject_heuristic"

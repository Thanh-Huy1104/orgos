import json
from pathlib import Path
from orgos.agile.sprint import Sprint, write_snapshot, read_snapshot


def test_write_and_read_snapshot(tmp_path):
    s = Sprint(
        id="s1", started_at="2026-07-01T00:00:00Z",
        repo_path=tmp_path, worktree_path=tmp_path / "wt",
        branch="agile/s1", picked_issue={"issue_id": "1"},
        envelopes={}, status="in_progress",
    )
    (tmp_path / "wt").mkdir()
    p = write_snapshot(s, backlog=[{"issue_id": "1"}], heuristics=[{"rule": "x"}])
    assert p.exists()
    data = read_snapshot("s1", base_dir=tmp_path)
    assert data["picked_issue"]["issue_id"] == "1"
    assert data["backlog"][0]["issue_id"] == "1"

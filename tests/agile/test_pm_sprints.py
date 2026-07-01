import json
from pathlib import Path

from orgos.pm import PMStore


def test_create_and_get_sprint(tmp_path: Path):
    pm = PMStore(tmp_path / "pm.db")
    pm.create_sprint("s1", "agile/s1", {"issue_id": "42"}, "in_progress")
    s = pm.get_sprint("s1")
    assert s is not None
    assert s["branch"] == "agile/s1"
    assert json.loads(s["picked_issue"])["issue_id"] == "42"
    assert s["status"] == "in_progress"


def test_record_envelope_and_update_status(tmp_path: Path):
    pm = PMStore(tmp_path / "pm.db")
    pm.create_sprint("s2", "agile/s2", {}, "in_progress")
    pm.record_sprint_envelope("s2", "brief", json.dumps({"x": 1}))
    pm.record_sprint_envelope("s2", "engineering", json.dumps({"y": 2}))
    pm.update_sprint_status("s2", "completed")
    s = pm.get_sprint("s2")
    assert s["status"] == "completed"
    envs = json.loads(s["envelopes_json"])
    assert "brief" in envs and "engineering" in envs


def test_list_sprints_orders_by_started_at_desc(tmp_path: Path):
    pm = PMStore(tmp_path / "pm.db")
    pm.create_sprint("a", "agile/a", {}, "completed")
    pm.create_sprint("b", "agile/b", {}, "completed")
    rows = pm.list_sprints(limit=10)
    assert [r["id"] for r in rows][:2] == ["b", "a"]


def test_create_sprint_accepts_explicit_started_at(tmp_path: Path):
    pm = PMStore(tmp_path / "pm.db")
    pm.create_sprint(
        "s3", "agile/s3", {}, "in_progress",
        started_at="2026-06-30T02:00:00+00:00",
    )
    s = pm.get_sprint("s3")
    assert s["started_at"] == "2026-06-30T02:00:00+00:00"

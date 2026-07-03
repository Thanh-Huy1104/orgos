from pathlib import Path
from orgos.pm import PMStore


def test_record_and_list_attribution(tmp_path: Path):
    pm = PMStore(tmp_path / "pm.db")
    pm.record_role_attribution("s1", "engineer", 0.4, 1.0, 0.6)
    rows = pm.list_role_attribution("engineer", since_days=30)
    assert rows[0]["score"] == 0.4


def test_create_adr_and_set_status(tmp_path: Path):
    pm = PMStore(tmp_path / "pm.db")
    aid = pm.create_adr(
        sprint_id="s1", kind="SPLIT_ROLE",
        before_yaml="a: 1\n", after_yaml="a: 2\n",
        rationale="clustering on canary",
    )
    rows = pm.list_adrs(status="pending")
    assert any(r["id"] == aid for r in rows)
    pm.set_adr_status(aid, "approved")
    rows = pm.list_adrs(status="approved")
    assert any(r["id"] == aid for r in rows)

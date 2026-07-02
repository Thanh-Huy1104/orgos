from pathlib import Path
from orgos.pm import PMStore


def test_record_and_latest(tmp_path: Path):
    pm = PMStore(tmp_path / "pm.db")
    pm.record_dora_snapshot({
        "window_days": 14, "deploy_freq": 1.2,
        "lead_time_p50": 18000.0, "cfr": 0.1,
        "mttr_p50": 3600.0, "tier": "Medium",
    })
    last = pm.latest_dora_snapshot()
    assert last["tier"] == "Medium"
    assert last["deploy_freq"] == 1.2


def test_list_desc(tmp_path):
    pm = PMStore(tmp_path / "pm.db")
    pm.record_dora_snapshot({"window_days": 14, "deploy_freq": 0.5,
        "lead_time_p50": 1.0, "cfr": 0.0, "mttr_p50": 0.0, "tier": "Low"})
    pm.record_dora_snapshot({"window_days": 14, "deploy_freq": 2.0,
        "lead_time_p50": 1.0, "cfr": 0.0, "mttr_p50": 0.0, "tier": "High"})
    rows = pm.list_dora_snapshots(limit=5)
    assert rows[0]["tier"] == "High"  # newest first

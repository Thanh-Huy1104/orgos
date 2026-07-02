import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from orgos.pm import PMStore
from orgos.agile.dora import classify_tier, compute_dora


def _iso(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def _seed(pm: PMStore, *, merges: int, pr_task_lag_days: float,
          failure_ratio: float, mttr_hours: float):
    for i in range(merges):
        task = pm.create_task(f"t{i}", department="engineering")
        # Force created_at to lag_days ago
        pm.conn.execute("UPDATE tasks SET created_at = ? WHERE id = ?",
                        (_iso(pr_task_lag_days), task.id))
        pm.record_git_op("pr_merged", details=task.id, pushed=True, task_id=task.id)
        pm.conn.execute("UPDATE git_ops SET created_at = ? WHERE task_id = ?",
                        (_iso(0.1), task.id))
        if i < int(merges * failure_ratio):
            pm.record_test_run("pytest", 1, "fail", passed=False, task_id=task.id)
            pm.conn.execute("UPDATE test_runs SET created_at = ? WHERE task_id = ?",
                            (_iso(0.05), task.id))
            pm.record_test_run("pytest", 0, "ok", passed=True, task_id=task.id)
            pm.conn.execute(
                "UPDATE test_runs SET created_at = ? "
                "WHERE task_id = ? AND passed = 1",
                (_iso(0.05 - mttr_hours / 24), task.id),
            )
    pm.conn.commit()


def test_deploy_freq_uses_window(tmp_path):
    pm = PMStore(tmp_path / "pm.db")
    _seed(pm, merges=14, pr_task_lag_days=1.0, failure_ratio=0.0, mttr_hours=0)
    m = compute_dora(pm, window_days=14)
    assert m["deploy_freq"] == pytest.approx(1.0, rel=0.01)


def test_lead_time_median(tmp_path):
    pm = PMStore(tmp_path / "pm.db")
    _seed(pm, merges=5, pr_task_lag_days=2.0, failure_ratio=0.0, mttr_hours=0)
    m = compute_dora(pm, window_days=14)
    # ~2 days in seconds
    assert 1.5 * 86400 < m["lead_time_p50"] < 2.5 * 86400


def test_cfr(tmp_path):
    pm = PMStore(tmp_path / "pm.db")
    _seed(pm, merges=10, pr_task_lag_days=1.0, failure_ratio=0.3, mttr_hours=1)
    m = compute_dora(pm, window_days=14)
    assert 0.25 <= m["cfr"] <= 0.35


def test_classify_tier_elite_when_hot():
    assert classify_tier({
        "deploy_freq": 1.5, "lead_time_p50": 3600.0,
        "cfr": 0.02, "mttr_p50": 900.0,
    }) == "Elite"


def test_classify_tier_low_when_cold():
    assert classify_tier({
        "deploy_freq": 0.01, "lead_time_p50": 30 * 86400.0,
        "cfr": 0.4, "mttr_p50": 30 * 3600.0,
    }) == "Low"

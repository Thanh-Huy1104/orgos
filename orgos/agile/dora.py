"""DORA metric computations over PMStore.

All four metrics use the same 14-day rolling window by default:
  - Deploy Frequency = count(pr_merged) / window_days
  - Lead Time (p50)  = median seconds between task.created_at and pr_merged.created_at
  - CFR              = fraction of merges followed by a failing test_run within 24h
  - MTTR (p50)       = median seconds from first fail to next pass, same task
"""

from __future__ import annotations

import statistics
from datetime import datetime, timezone, timedelta
from typing import Any


TIER_THRESHOLDS = {
    "Elite":  {"deploy_freq": 1.0,  "lead_time_p50": 86400.0,     "cfr": 0.05, "mttr_p50": 3600.0},
    "High":   {"deploy_freq": 0.14, "lead_time_p50": 7 * 86400.0, "cfr": 0.10, "mttr_p50": 86400.0},
    "Medium": {"deploy_freq": 0.03, "lead_time_p50": 30 * 86400.0, "cfr": 0.15, "mttr_p50": 7 * 86400.0},
}


def _parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def compute_dora(pm: Any, window_days: int = 14) -> dict:
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=window_days)

    merges = pm.conn.execute(
        "SELECT id, task_id, created_at FROM git_ops "
        "WHERE operation = 'pr_merged' AND pushed = 1 AND created_at >= ?",
        (start.isoformat(),),
    ).fetchall()

    deploy_freq = len(merges) / window_days if window_days else 0.0

    lead_times: list[float] = []
    for m in merges:
        if not m["task_id"]:
            continue
        row = pm.conn.execute(
            "SELECT created_at FROM tasks WHERE id = ?", (m["task_id"],),
        ).fetchone()
        if not row:
            continue
        lead_times.append(
            (_parse_iso(m["created_at"]) - _parse_iso(row["created_at"])).total_seconds()
        )
    lead_time_p50 = statistics.median(lead_times) if lead_times else 0.0

    fail_within_24h = 0
    mttrs: list[float] = []
    for m in merges:
        merge_at = _parse_iso(m["created_at"])
        fails = pm.conn.execute(
            "SELECT created_at FROM test_runs "
            "WHERE task_id = ? AND passed = 0 AND created_at >= ? "
            "ORDER BY created_at ASC",
            (m["task_id"], merge_at.isoformat()),
        ).fetchall()
        if fails and _parse_iso(fails[0]["created_at"]) - merge_at <= timedelta(hours=24):
            fail_within_24h += 1
            first_fail = _parse_iso(fails[0]["created_at"])
            recovery = pm.conn.execute(
                "SELECT created_at FROM test_runs "
                "WHERE task_id = ? AND passed = 1 AND created_at >= ? "
                "ORDER BY created_at ASC LIMIT 1",
                (m["task_id"], first_fail.isoformat()),
            ).fetchone()
            if recovery:
                mttrs.append(
                    (_parse_iso(recovery["created_at"]) - first_fail).total_seconds()
                )
    cfr = fail_within_24h / len(merges) if merges else 0.0
    mttr_p50 = statistics.median(mttrs) if mttrs else 0.0

    metrics = {
        "window_days": window_days,
        "deploy_freq": round(deploy_freq, 3),
        "lead_time_p50": round(lead_time_p50, 1),
        "cfr": round(cfr, 3),
        "mttr_p50": round(mttr_p50, 1),
    }
    metrics["tier"] = classify_tier(metrics)
    return metrics


def classify_tier(m: dict) -> str:
    """Highest tier whose ALL four thresholds the metrics meet."""
    for tier in ("Elite", "High", "Medium"):
        t = TIER_THRESHOLDS[tier]
        if (m["deploy_freq"] >= t["deploy_freq"]
                and m["lead_time_p50"] <= t["lead_time_p50"]
                and m["cfr"] <= t["cfr"]
                and m["mttr_p50"] <= t["mttr_p50"]):
            return tier
    return "Low"

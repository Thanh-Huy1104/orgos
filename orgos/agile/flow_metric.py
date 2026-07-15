"""Scrum flow-efficiency metrics — sprint-level measurement.

Operationalises the takt-time / velocity-delta lineage from the reference
spec (§0). All input data (sprint timestamps, issue counts) comes from
PMStore. Runs alongside rubric.py and dora.py — no metric replaces another.

Usage:
    from orgos.agile.flow_metric import flow_score
    score = flow_score(pm, sprint_id)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


def takt_time(duration_seconds: float, n_issues: int) -> float:
    """Average calendar time per issue. Lower = faster flow.

    Returns 0.0 if no issues were processed (degenerate sprint).
    """
    if n_issues <= 0:
        return 0.0
    return duration_seconds / max(n_issues, 1)


def velocity_delta(
    expected_finish_iso: str,
    actual_finish_iso: str,
) -> float:
    """Seconds between expected and actual finish.

    Positive = finished early (ahead of schedule).
    Negative = finished late (behind schedule).
    Zero = exactly on time.
    """
    try:
        expected = datetime.fromisoformat(expected_finish_iso)
        actual = datetime.fromisoformat(actual_finish_iso)
    except (ValueError, TypeError):
        return 0.0
    delta = (expected - actual).total_seconds()
    return delta


@dataclass
class FlowMetricResult:
    sprint_id: str
    duration_seconds: float
    n_issues: int
    takt_time: float
    velocity_delta: float
    flow_score: float = 0.0
    warnings: list[str] = field(default_factory=list)


def compute_flow_metrics(
    *,
    sprint_id: str,
    started_at_iso: str,
    completed_at_iso: str | None = None,
    n_issues: int = 0,
    expected_finish_iso: str | None = None,
) -> FlowMetricResult:
    started = _parse_iso(started_at_iso)
    completed = _parse_iso(completed_at_iso) if completed_at_iso else _now_utc()

    duration = (completed - started).total_seconds()
    t_time = takt_time(duration, n_issues)

    v_delta = 0.0
    if expected_finish_iso:
        v_delta = velocity_delta(expected_finish_iso, completed.isoformat())

    score = _aggregate(t_time, v_delta, n_issues)

    warnings: list[str] = []
    if duration > 8 * 3600:
        warnings.append(f"sprint duration ({duration/3600:.1f}h) exceeds 8h")
    if t_time > 14_400:
        warnings.append(f"takt time ({t_time/3600:.1f}h) exceeds 4h per issue")
    if v_delta < -3600:
        warnings.append(f"velocity delta ({v_delta/3600:.1f}h) behind schedule")

    return FlowMetricResult(
        sprint_id=sprint_id,
        duration_seconds=duration,
        n_issues=n_issues,
        takt_time=round(t_time, 1),
        velocity_delta=round(v_delta, 1),
        flow_score=round(score, 3),
        warnings=warnings,
    )


def _aggregate(takt: float, v_delta: float, n_issues: int) -> float:
    """Combine takt-time and velocity-delta into a single flow score.

    Score range: roughly 0.0 (poor) to 1.0+ (excellent).

    Components:
      - Takt: 4h target → 4h = 0.5, 1h = 1.0, >8h → <0.25
      - Velocity: on-schedule = 0.5, 1h ahead = 0.75, 1h behind = 0.25
      - Throughput: 1 issue = 0.5, 3+ = 1.0

    Formula is a working reconstruction and may need external confirmation.
    """
    if n_issues <= 0:
        return 0.0

    takt_hours = takt / 3600.0
    takt_component = max(0.0, min(1.0, 4.0 / max(takt_hours, 0.25)))

    delta_hours = v_delta / 3600.0
    velocity_component = 0.5 + max(-0.5, min(0.5, delta_hours / 2.0))

    throughput_component = min(1.0, n_issues / 3.0)

    return takt_component * 0.40 + velocity_component * 0.30 + throughput_component * 0.30


def _parse_iso(s: str | None) -> datetime:
    if not s:
        return _now_utc()
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return _now_utc()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)

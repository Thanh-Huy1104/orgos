"""Tests for flow-efficiency metrics (Plan 5)."""

from __future__ import annotations

from orgos.agile.flow_metric import (
    FlowMetricResult,
    compute_flow_metrics,
    takt_time,
    velocity_delta,
)


class TestTaktTime:
    def test_four_hours_for_one_issue(self):
        t = takt_time(4 * 3600, 1)
        assert t == 14400.0

    def test_two_hours_per_issue(self):
        t = takt_time(8 * 3600, 4)
        assert t == 7200.0

    def test_zero_issues_returns_zero(self):
        t = takt_time(3600, 0)
        assert t == 0.0

    def test_negative_issues_returns_zero(self):
        t = takt_time(3600, -1)
        assert t == 0.0


class TestVelocityDelta:
    def test_finished_early_positive(self):
        d = velocity_delta("2026-01-01T06:00:00+00:00", "2026-01-01T04:00:00+00:00")
        assert d == 7200.0  # 2h ahead

    def test_finished_late_negative(self):
        d = velocity_delta("2026-01-01T04:00:00+00:00", "2026-01-01T06:00:00+00:00")
        assert d == -7200.0  # 2h behind

    def test_finished_exactly_on_time(self):
        d = velocity_delta("2026-01-01T04:00:00+00:00", "2026-01-01T04:00:00+00:00")
        assert d == 0.0

    def test_invalid_iso_returns_zero(self):
        d = velocity_delta("not-a-date", "2026-01-01T04:00:00+00:00")
        assert d == 0.0

    def test_handles_z_suffix(self):
        d = velocity_delta("2026-01-01T06:00:00Z", "2026-01-01T04:00:00Z")
        assert d == 7200.0


class TestComputeFlowMetrics:
    def test_typical_sprint(self):
        result = compute_flow_metrics(
            sprint_id="s1",
            started_at_iso="2026-01-01T00:00:00+00:00",
            completed_at_iso="2026-01-01T04:00:00+00:00",
            n_issues=2,
            expected_finish_iso="2026-01-01T04:00:00+00:00",
        )
        assert isinstance(result, FlowMetricResult)
        assert result.sprint_id == "s1"
        assert result.duration_seconds == 14400.0
        assert result.n_issues == 2
        assert result.takt_time == 7200.0
        assert result.velocity_delta == 0.0
        assert 0.0 <= result.flow_score <= 1.0

    def test_sprint_with_few_issues_lower_score(self):
        many = compute_flow_metrics(
            sprint_id="s_many",
            started_at_iso="2026-01-01T00:00:00+00:00",
            completed_at_iso="2026-01-01T04:00:00+00:00",
            n_issues=4,
        )
        few = compute_flow_metrics(
            sprint_id="s_few",
            started_at_iso="2026-01-01T00:00:00+00:00",
            completed_at_iso="2026-01-01T04:00:00+00:00",
            n_issues=1,
        )
        assert many.flow_score > few.flow_score

    def test_zero_issues_returns_zero_score(self):
        result = compute_flow_metrics(
            sprint_id="s0",
            started_at_iso="2026-01-01T00:00:00+00:00",
            completed_at_iso="2026-01-01T04:00:00+00:00",
            n_issues=0,
        )
        assert result.flow_score == 0.0

    def test_long_sprint_generates_warnings(self):
        result = compute_flow_metrics(
            sprint_id="s_long",
            started_at_iso="2026-01-01T00:00:00+00:00",
            completed_at_iso="2026-01-01T12:00:00+00:00",
            n_issues=1,
        )
        assert len(result.warnings) > 0

    def test_behind_schedule_generates_warning(self):
        result = compute_flow_metrics(
            sprint_id="s_late",
            started_at_iso="2026-01-01T00:00:00+00:00",
            completed_at_iso="2026-01-01T06:00:00+00:00",
            n_issues=1,
            expected_finish_iso="2026-01-01T04:00:00+00:00",
        )
        assert len(result.warnings) > 0

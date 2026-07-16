"""Tests for Sprint Process Efficiency (SPE) — the time-proportional metric."""

from __future__ import annotations

from types import SimpleNamespace

from orgos.agile.spe import (
    process_efficiency,
    sprint_process_efficiency,
    spe_band,
)


def _story(issue_id, points, state, activated="", closed=""):
    return SimpleNamespace(
        issue_id=issue_id, points=points, state=state,
        activated_at=activated, closed_at=closed,
    )


class TestProcessEfficiency:
    def test_done_story_on_pace_pe_is_one(self):
        # 5 pts of a 10-pt commitment over a 10h sprint → ideal 5h. Took 5h.
        s = _story("A", 5, "done",
                   "2026-01-01T00:00:00Z", "2026-01-01T05:00:00Z")
        assert process_efficiency(s, duration_hours=10, final_commit=10) == 1.0

    def test_fast_story_pe_above_one(self):
        s = _story("A", 5, "done",
                   "2026-01-01T00:00:00Z", "2026-01-01T02:00:00Z")
        # ideal 5h / actual 2h = 2.5
        assert process_efficiency(s, duration_hours=10, final_commit=10) == 2.5

    def test_incomplete_story_pe_zero(self):
        s = _story("A", 5, "in_progress",
                   "2026-01-01T00:00:00Z", "")
        assert process_efficiency(s, duration_hours=10, final_commit=10) == 0.0

    def test_missing_timestamps_pe_zero(self):
        s = _story("A", 5, "done")
        assert process_efficiency(s, duration_hours=10, final_commit=10) == 0.0

    def test_zero_duration_pe_zero(self):
        s = _story("A", 5, "done",
                   "2026-01-01T00:00:00Z", "2026-01-01T05:00:00Z")
        assert process_efficiency(s, duration_hours=0, final_commit=10) == 0.0

    def test_zero_actual_time_pe_zero(self):
        s = _story("A", 5, "done",
                   "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z")
        assert process_efficiency(s, duration_hours=10, final_commit=10) == 0.0


class TestSprintProcessEfficiency:
    def test_weighted_average(self):
        a = _story("A", 5, "done",
                   "2026-01-01T00:00:00Z", "2026-01-01T02:00:00Z")  # PE 2.5
        b = _story("B", 5, "done",
                   "2026-01-01T00:00:00Z", "2026-01-01T08:00:00Z")  # PE 0.625
        r = sprint_process_efficiency([a, b], duration_hours=10)
        assert r["final_commit"] == 10
        assert r["spe"] == 1.5625
        assert r["scored_stories"] == 2

    def test_incomplete_counts_in_commit_but_pe_zero(self):
        a = _story("A", 5, "done",
                   "2026-01-01T00:00:00Z", "2026-01-01T02:00:00Z")  # PE 2.5
        c = _story("C", 5, "in_progress", "2026-01-01T00:00:00Z", "")
        r = sprint_process_efficiency([a, c], duration_hours=10)
        assert r["final_commit"] == 10           # commitment includes incomplete
        assert r["spe"] == 1.25                   # (2.5*5 + 0*5)/10

    def test_blocked_excluded_from_commit_and_average(self):
        a = _story("A", 5, "done",
                   "2026-01-01T00:00:00Z", "2026-01-01T05:00:00Z")  # PE 1.0
        d = _story("D", 3, "blocked")
        r = sprint_process_efficiency([a, d], duration_hours=10)
        assert r["final_commit"] == 5             # blocked dropped from commit
        assert r["dropped_stories"] == 1
        assert r["spe"] == 1.0

    def test_empty_sprint_spe_zero(self):
        r = sprint_process_efficiency([], duration_hours=10)
        assert r["spe"] == 0.0
        assert r["final_commit"] == 0


class TestSpeBand:
    def test_bands(self):
        assert spe_band(0.0) == "No Delivery"
        assert spe_band(0.10) == "Needs Improvement"
        assert spe_band(0.40) == "Good"
        assert spe_band(0.60) == "Excellent"
        assert spe_band(1.20) == "Verify Data"

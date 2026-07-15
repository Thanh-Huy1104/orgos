"""Tests for paired dual-team benchmarking (Plan 5)."""

from __future__ import annotations

from pathlib import Path

import pytest

from orgos.agile.paired_run import (
    PairedRunReport,
    TeamRunResult,
    _compare_teams,
    run_paired_benchmark,
)


class TestCompareTeams:
    def test_team_a_wins_on_rubric(self):
        a = TeamRunResult(team_name="alpha", sprint_id="s1",
                          started_at="t", completed_at="t",
                          status="completed", rubric_score=0.95, flow_score=0.8)
        b = TeamRunResult(team_name="beta", sprint_id="s2",
                          started_at="t", completed_at="t",
                          status="completed", rubric_score=0.80, flow_score=0.7)
        winner, sd, fd = _compare_teams(a, b)
        assert winner == "alpha"
        assert sd > 0

    def test_team_b_wins(self):
        a = TeamRunResult(team_name="alpha", sprint_id="s1",
                          started_at="t", completed_at="t",
                          status="completed", rubric_score=0.70, flow_score=0.6)
        b = TeamRunResult(team_name="beta", sprint_id="s2",
                          started_at="t", completed_at="t",
                          status="completed", rubric_score=0.90, flow_score=0.9)
        winner, sd, fd = _compare_teams(a, b)
        assert winner == "beta"
        assert sd < 0

    def test_tie_when_scores_close(self):
        a = TeamRunResult(team_name="alpha", sprint_id="s1",
                          started_at="t", completed_at="t",
                          status="completed", rubric_score=0.85, flow_score=0.8)
        b = TeamRunResult(team_name="beta", sprint_id="s2",
                          started_at="t", completed_at="t",
                          status="completed", rubric_score=0.86, flow_score=0.8)
        winner, sd, fd = _compare_teams(a, b)
        assert winner == "tie"

    def test_none_scores_handled(self):
        a = TeamRunResult(team_name="alpha", sprint_id="s1",
                          started_at="t", completed_at="t",
                          status="completed")
        b = TeamRunResult(team_name="beta", sprint_id="s2",
                          started_at="t", completed_at="t",
                          status="completed")
        winner, sd, fd = _compare_teams(a, b)
        assert winner == "tie"
        assert sd == 0.0


class TestPairedBenchmark:
    def test_offline_mode_produces_report(self, tmp_path: Path):
        issue = {"issue_id": "42", "title": "Test issue"}
        report = run_paired_benchmark(
            repo_path=tmp_path,
            issue=issue,
            agents_dir_a=tmp_path / "agents_a",
            agents_dir_b=tmp_path / "agents_b",
            _offline=True,
        )
        assert isinstance(report, PairedRunReport)
        assert report.issue_id == "42"
        assert report.repo_sha == "deadbeef"
        assert report.team_a.team_name == "topology-a"
        assert report.team_b.team_name == "topology-b"

    def test_report_has_summary(self, tmp_path: Path):
        issue = {"issue_id": "1", "title": "T"}
        report = run_paired_benchmark(
            repo_path=tmp_path,
            issue=issue,
            agents_dir_a=tmp_path / "a",
            agents_dir_b=tmp_path / "b",
            _offline=True,
        )
        assert report.summary
        assert "rubric delta" in report.summary


class TestTeamRunResult:
    def test_default_values(self):
        r = TeamRunResult(team_name="t", sprint_id="s",
                          started_at="st", completed_at="ct",
                          status="completed")
        assert r.rubric_score is None
        assert r.dora_tier == ""
        assert r.flow_score == 0.0

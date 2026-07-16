"""Tests for HEARTBEAT.md natural-language schedule parsing."""

from __future__ import annotations

import pytest

from orgos.agile.heartbeat_scheduler import (
    HeartbeatScheduler, ScheduledTask, parse_schedule,
)


class TestParseSchedule:
    def test_every_n_seconds(self):
        text = """
        # arch heartbeat
        ## Every 30 seconds
        Check the board.
        """
        tasks = parse_schedule(text)
        assert len(tasks) == 1
        assert tasks[0].cadence_seconds == 30
        assert "Check the board" in tasks[0].action_text

    def test_every_n_minutes(self):
        text = "## Every 5 minutes\nRun poker."
        tasks = parse_schedule(text)
        assert tasks[0].cadence_seconds == 300

    def test_every_n_hours(self):
        text = "## Every 4 hours\nWrite retro."
        tasks = parse_schedule(text)
        assert tasks[0].cadence_seconds == 14400

    def test_multiple_tasks(self):
        text = """
        ## Every 30 seconds
        Check the board.

        ## Every 30 minutes
        Poll PR comments.
        """
        tasks = parse_schedule(text)
        assert len(tasks) == 2
        assert tasks[0].cadence_seconds == 30
        assert tasks[1].cadence_seconds == 1800

    def test_ignores_non_schedule_headers(self):
        text = """
        ## Instructions
        Some prose.

        ## Every 60 seconds
        A task.
        """
        assert len(parse_schedule(text)) == 1

    def test_empty_input(self):
        assert parse_schedule("") == []
        assert parse_schedule("Just some prose, no schedule.") == []


class TestHeartbeatScheduler:
    def test_first_tick_fires_all_tasks(self):
        text = "## Every 30 seconds\nCheck board.\n\n## Every 5 minutes\nPoker."
        sched = HeartbeatScheduler(text)
        due = sched.pending(now_seconds=0.0)
        assert len(due) == 2

    def test_second_tick_only_fires_ready_tasks(self):
        text = "## Every 30 seconds\nCheck board.\n\n## Every 5 minutes\nPoker."
        sched = HeartbeatScheduler(text)
        sched.pending(now_seconds=0.0)   # arms both
        due = sched.pending(now_seconds=30.0)
        # Only the 30-second one should fire again; poker at 300s not yet due
        assert len(due) == 1
        assert due[0].cadence_seconds == 30

    def test_next_tick_in(self):
        text = "## Every 30 seconds\nCheck.\n\n## Every 5 minutes\nPoker."
        sched = HeartbeatScheduler(text)
        sched.pending(now_seconds=0.0)
        # Next tick should be 30s from now
        assert sched.next_tick_in(now_seconds=0.0) == pytest.approx(30.0)

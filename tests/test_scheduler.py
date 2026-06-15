"""Tests for orgos.scheduler — Scheduler, cadence logic, notifications.

No LLM key required — tests the scheduling logic and state tracking.
"""

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from orgos import (
    Org,
    SOP,
    Department,
    PermissionTier,
    RoleSpec,
    Scheduler,
    TaskBrief,
)


@pytest.fixture
def org_with_jobs():
    """An org with one department, two scheduled SOPs."""
    supervisor = RoleSpec(
        name="lead",
        tier=PermissionTier.ORCHESTRATOR,
        system_prompt="Lead.",
        model="gpt-4o-mini",
    )
    daily = SOP(
        name="daily_scan",
        brief=TaskBrief(objective="Daily scan"),
        cadence="daily",
    )
    weekly = SOP(
        name="weekly_report",
        brief=TaskBrief(objective="Weekly report"),
        cadence="weekly",
    )
    ondemand = SOP(
        name="adhoc",
        brief=TaskBrief(objective="Ad-hoc task"),
        cadence=None,
    )
    dept = Department(
        name="finance",
        supervisor=supervisor,
        sops=[daily, weekly, ondemand],
    )
    return Org(name="TestOrg", departments=[dept])


@pytest.fixture
def scheduler(org_with_jobs):
    db = tempfile.mktemp(suffix=".db")
    org_with_jobs.use_memory(db)
    s = Scheduler(org_with_jobs)
    yield s
    s.memory.close()
    Path(db).unlink(missing_ok=True)


# ── Job listing ─────────────────────────────────────────────────────────────


class TestJobListing:
    def test_lists_scheduled_jobs(self, scheduler):
        jobs = scheduler.jobs()
        assert len(jobs) == 2  # daily + weekly, not ondemand
        names = {(j.department.name, j.sop_name) for j in jobs}
        assert ("finance", "daily_scan") in names
        assert ("finance", "weekly_report") in names

    def test_ondemand_not_scheduled(self, scheduler):
        cadences = {j.cadence for j in scheduler.jobs()}
        assert None not in cadences

    def test_empty_org(self):
        org = Org(name="Empty")
        org.use_memory(tempfile.mktemp(suffix=".db"))
        s = Scheduler(org)
        assert s.jobs() == []
        s.memory.close()


# ── Cadence logic ───────────────────────────────────────────────────────────


class TestCadenceLogic:
    def test_never_run_is_due(self, scheduler):
        """A job that has never run should be due."""
        entry = scheduler.jobs()[0]  # daily_scan
        now = datetime.now(timezone.utc)
        assert scheduler._is_due(entry, now) is True

    def test_already_run_today_not_due(self, scheduler):
        """After running today, daily job should not be due again."""
        entry = scheduler.jobs()[0]  # daily_scan
        now = datetime.now(timezone.utc)
        # Simulate having run just now
        last_key = f"sched_last:{entry.department.name}:{entry.sop_name}"
        scheduler.memory.set_preference(last_key, now.isoformat())
        assert scheduler._is_due(entry, now) is False

    def test_run_yesterday_is_due(self, scheduler):
        """If last run was yesterday, daily job is due today."""
        entry = scheduler.jobs()[0]  # daily_scan
        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        last_key = f"sched_last:{entry.department.name}:{entry.sop_name}"
        scheduler.memory.set_preference(last_key, yesterday.isoformat())
        now = datetime.now(timezone.utc)
        assert scheduler._is_due(entry, now) is True

    def test_weekly_not_due_same_week(self, scheduler):
        """Weekly job run today should not be due today."""
        entry = [j for j in scheduler.jobs() if j.cadence == "weekly"][0]
        now = datetime.now(timezone.utc)
        last_key = f"sched_last:{entry.department.name}:{entry.sop_name}"
        scheduler.memory.set_preference(last_key, now.isoformat())
        assert scheduler._is_due(entry, now) is False

    def test_weekly_due_after_8_days(self, scheduler):
        """Weekly job run 8 days ago should be due."""
        entry = [j for j in scheduler.jobs() if j.cadence == "weekly"][0]
        eight_days_ago = datetime.now(timezone.utc) - timedelta(days=8)
        last_key = f"sched_last:{entry.department.name}:{entry.sop_name}"
        scheduler.memory.set_preference(last_key, eight_days_ago.isoformat())
        now = datetime.now(timezone.utc)
        assert scheduler._is_due(entry, now) is True

    def test_no_cadence_not_due(self, scheduler):
        """SOPs without cadence should never be due."""
        # All scheduled jobs have a cadence; test the logic directly
        from orgos.scheduler import ScheduleEntry
        dept = scheduler.org.departments[0]
        entry = ScheduleEntry(dept, "adhoc", None)
        now = datetime.now(timezone.utc)
        assert scheduler._is_due(entry, now) is False

    def test_on_startup_only_runs_once(self, scheduler):
        """on_startup cadence should only fire the first time."""
        from orgos.scheduler import ScheduleEntry
        dept = scheduler.org.departments[0]
        entry = ScheduleEntry(dept, "init", "on_startup")
        now = datetime.now(timezone.utc)
        # First time: due
        assert scheduler._is_due(entry, now) is True
        # After recording: not due
        last_key = "sched_last:finance:init"
        scheduler.memory.set_preference(last_key, now.isoformat())
        assert scheduler._is_due(entry, now) is False


# ── Notification hooks ──────────────────────────────────────────────────────


class TestNotifications:
    def test_notify_terminal(self, capsys):
        from orgos.scheduler import notify_owner
        org = Org(name="TestOrg")
        notify_owner(org, "test_event", "Something happened.", level="warning")
        captured = capsys.readouterr()
        assert "TestOrg" in captured.out
        assert "TEST_EVENT" in captured.out
        assert "Something happened" in captured.out

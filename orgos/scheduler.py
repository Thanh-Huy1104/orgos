"""Scheduler — the production calendar for the org.

Reads SOP cadences from the org constitution, runs departments on
schedule, records results to OrgMemory, and surfaces alerts to the
owner via notification hooks.

Usage::

    from orgos import load_org, Scheduler

    org = load_org("config/org.yaml")
    scheduler = Scheduler(org)
    scheduler.run_pending()       # run everything that's due now
    scheduler.run_loop()          # run continuously, checking every 60s
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .departments import Department, Org


# ── Notification ──────────────────────────────────────────────────────────────


def notify_owner(
    org: Org,
    event: str,
    message: str,
    *,
    level: str = "info",  # "info", "warning", "critical"
) -> None:
    """Surface an event to the owner via the configured channel.

    Currently terminal-only. Pluggable for Slack/email/webhook later.
    """
    cfg = org.notification
    prefix = {"info": "ℹ", "warning": "⚠", "critical": "🔴"}.get(level, "•")

    if cfg.type == "terminal":
        print(f"\n{prefix} [{org.name}] [{event.upper()}] {message}")
    # Future: elif cfg.type == "slack": ...
    # Future: elif cfg.type == "email": ...


# ── Schedule entry ────────────────────────────────────────────────────────────


@dataclass
class ScheduleEntry:
    """A single scheduled job — one SOP in one department."""

    department: Department
    sop_name: str
    cadence: str | None  # "daily", "weekly", "hourly", "cron:...", or None


# ── Scheduler ─────────────────────────────────────────────────────────────────


class Scheduler:
    """Runs the org on a production calendar.

    Each SOP with a cadence becomes a scheduled job.  Run history and
    last-run timestamps are stored in OrgMemory.
    """

    def __init__(self, org: Org):
        self.org = org
        self.memory = org.use_memory()
        self._approval_fn: Any = None
        # Extra callable jobs registered via add_job(); each entry is a dict:
        # {"fn": callable, "cadence": str, "id": str, "misfire_grace_time": int}
        self._callable_jobs: list[dict[str, Any]] = []

    # ── Public API ────────────────────────────────────────────────────────

    def set_approval(self, fn: Any) -> None:
        """Set the approval function used for gated actions."""
        self._approval_fn = fn

    def add_job(
        self,
        fn: Callable[[], Any],
        *,
        trigger: str = "cron",
        hour: int = 0,
        minute: int = 0,
        id: str | None = None,
        misfire_grace_time: int = 600,
    ) -> None:
        """Register a plain callable as a scheduled job.

        Only ``trigger="cron"`` is supported; hour/minute map to a cron
        expression ``"cron: <minute> <hour> * * *"``.
        """
        if trigger != "cron":
            raise ValueError(f"Unsupported trigger type: {trigger!r}")
        cadence = f"cron: {minute} {hour} * * *"
        self._callable_jobs.append(
            {
                "fn": fn,
                "cadence": cadence,
                "id": id or fn.__name__,
                "misfire_grace_time": misfire_grace_time,
            }
        )

    def jobs(self) -> list[ScheduleEntry]:
        """Return all scheduled jobs from the org constitution."""
        entries: list[ScheduleEntry] = []
        for dept in self.org.departments:
            for sop in dept.sops:
                if sop.cadence:
                    entries.append(ScheduleEntry(dept, sop.name, sop.cadence))
        return entries

    def run_pending(self) -> list[dict[str, Any]]:
        """Run every job whose cadence says it's due right now.

        Returns a list of result summaries.
        """
        results: list[dict[str, Any]] = []
        now = datetime.now(timezone.utc)

        for entry in self.jobs():
            if self._is_due(entry, now):
                result = self._execute_job(entry)
                results.append(result)

        for job in self._callable_jobs:
            last_key = f"sched_last:callable:{job['id']}"
            last_ts = self.memory.get_preference(last_key)
            if self._cron_due(job["cadence"][len("cron:"):].strip(), last_ts, now):
                result = self._execute_callable_job(job)
                results.append(result)

        return results

    def run_loop(
        self,
        interval_sec: int = 60,
        *,
        max_iterations: int | None = None,
    ) -> None:
        """Run continuously, checking for due jobs every *interval_sec*.

        Set *max_iterations* to stop after N cycles (useful for testing).
        """
        iteration = 0
        notify_owner(
            self.org,
            "scheduler_started",
            f"{len(self.jobs())} jobs loaded, checking every {interval_sec}s",
        )

        try:
            while max_iterations is None or iteration < max_iterations:
                results = self.run_pending()
                for r in results:
                    self._check_alerts(r)

                iteration += 1
                time.sleep(interval_sec)
        except KeyboardInterrupt:
            notify_owner(self.org, "scheduler_stopped", "Shutting down.")
        finally:
            self.memory.close()

    # ── Internals ──────────────────────────────────────────────────────────

    def _is_due(self, entry: ScheduleEntry, now: datetime) -> bool:
        """Check if a job is due based on its cadence and last-run timestamp."""
        last_key = f"sched_last:{entry.department.name}:{entry.sop_name}"
        last_ts = self.memory.get_preference(last_key)

        if entry.cadence in (None, ""):
            return False

        # "cron: * * * * *" — would need a cron parser; skip for now
        if entry.cadence.startswith("cron:"):
            return self._cron_due(entry.cadence[5:].strip(), last_ts, now)

        last_dt = datetime.fromisoformat(last_ts) if last_ts else None
        if last_dt is None:
            return True  # never run

        # Check based on cadence type
        if entry.cadence == "hourly":
            return (now - last_dt).total_seconds() >= 3600
        elif entry.cadence == "daily":
            return now.date() > last_dt.date()
        elif entry.cadence == "weekly":
            return (now - last_dt).days >= 7
        elif entry.cadence == "on_startup":
            # Run once per process lifetime — already ran if last_ts exists
            return False

        return False

    def _cron_due(
        self, expr: str, last_ts: str | None, now: datetime
    ) -> bool:
        """Minimal cron support: minute hour day month weekday."""
        try:
            parts = expr.strip().split()
            if len(parts) != 5:
                return False
            # Very simple: just check if it's been more than 1 minute since last run
            if last_ts is None:
                return True
            last_dt = datetime.fromisoformat(last_ts)
            return (now - last_dt).total_seconds() >= 60
        except Exception:
            return False

    def _execute_job(self, entry: ScheduleEntry) -> dict[str, Any]:
        """Execute one scheduled job via run_department()."""
        from .departments import run_department

        sop = entry.department.find_sop(entry.sop_name)
        if sop is None:
            return {
                "department": entry.department.name,
                "sop": entry.sop_name,
                "error": "SOP not found",
            }

        notify_owner(
            self.org,
            "job_started",
            f"{entry.department.name}/{entry.sop_name} (cadence={entry.cadence})",
        )

        try:
            result = run_department(
                self.org,
                entry.department.name,
                sop.brief,
                approval_fn=self._approval_fn,
                verbose=False,
                record=True,
            )
        except Exception as exc:
            notify_owner(
                self.org,
                "job_failed",
                f"{entry.department.name}/{entry.sop_name}: {exc}",
                level="critical",
            )
            return {
                "department": entry.department.name,
                "sop": entry.sop_name,
                "status": "error",
                "error": str(exc),
            }

        # Record last-run timestamp
        last_key = f"sched_last:{entry.department.name}:{entry.sop_name}"
        self.memory.set_preference(
            last_key, datetime.now(timezone.utc).isoformat()
        )

        status = result.envelope.status
        tokens = (
            result.token_usage.get("total_tokens", 0)
            if result.token_usage
            else 0
        )

        notify_owner(
            self.org,
            "job_completed",
            f"{entry.department.name}/{entry.sop_name}: "
            f"status={status} tokens={tokens:,}",
            level="warning" if status != "completed" else "info",
        )

        return {
            "department": entry.department.name,
            "sop": entry.sop_name,
            "status": status,
            "tokens": tokens,
            "summary": result.envelope.summary[:200],
        }

    def _execute_callable_job(self, job: dict[str, Any]) -> dict[str, Any]:
        """Execute a plain callable registered via add_job()."""
        job_id = job["id"]
        notify_owner(
            self.org,
            "job_started",
            f"callable/{job_id} (cadence={job['cadence']})",
        )
        try:
            job["fn"]()
        except Exception as exc:
            notify_owner(
                self.org,
                "job_failed",
                f"callable/{job_id}: {exc}",
                level="critical",
            )
            return {"job_id": job_id, "status": "error", "error": str(exc)}

        last_key = f"sched_last:callable:{job_id}"
        self.memory.set_preference(last_key, datetime.now(timezone.utc).isoformat())
        notify_owner(self.org, "job_completed", f"callable/{job_id}: ok")
        return {"job_id": job_id, "status": "completed"}

    def _check_alerts(self, result: dict[str, Any]) -> None:
        """Check notification thresholds after a job completes."""
        owner = self.org.owner
        thresholds = owner.notification_thresholds

        # Check consecutive failures
        if thresholds.consecutive_failures:
            recent = self.memory.recent_runs(
                department=result["department"], limit=thresholds.consecutive_failures
            )
            if len(recent) >= thresholds.consecutive_failures:
                if all(r.status != "completed" for r in recent):
                    notify_owner(
                        self.org,
                        "threshold_breach",
                        f"{result['department']}: {thresholds.consecutive_failures} "
                        f"consecutive failures — last: {recent[0].summary[:100]}",
                        level="critical",
                    )

        # Check token spend
        if thresholds.token_spend_daily:
            spend = self.memory.department_spend(
                result["department"], days=1
            )
            if spend["total_tokens"] > thresholds.token_spend_daily:
                notify_owner(
                    self.org,
                    "threshold_breach",
                    f"{result['department']}: daily token spend "
                    f"({spend['total_tokens']:,}) exceeds threshold "
                    f"({thresholds.token_spend_daily:,})",
                    level="warning",
                )

            # Budget exceeded percentage alert
            if self.org.default_max_budget_tokens:
                pct = int(
                    spend["total_tokens"]
                    / self.org.default_max_budget_tokens
                    * 100
                )
                if pct >= thresholds.budget_exceeded_pct:
                    notify_owner(
                        self.org,
                        "threshold_breach",
                        f"{result['department']}: at {pct}% of budget "
                        f"({spend['total_tokens']:,} / "
                        f"{self.org.default_max_budget_tokens:,})",
                        level="warning",
                    )


# ── Nightly agile sprint ─────────────────────────────────────────────────────


def nightly_agile_sprint(repo_path: str = ".") -> None:
    """Run one sprint against the agile backlog. Logs to PMStore."""
    from orgos.agile.sprint import run_nightly_sprint
    print(f"[{datetime.now().isoformat()}] starting nightly agile sprint")
    sprint = run_nightly_sprint(Path(repo_path), mock_pr=False)
    print(f"  done: sprint_id={sprint.id} status={sprint.status}")


def register_nightly_jobs(scheduler: "Scheduler") -> None:
    """Wire the 02:00 nightly sprint into *scheduler*.

    Call this after constructing a Scheduler to activate the agile cron job::

        org = load_org("config/org.yaml")
        s = Scheduler(org)
        register_nightly_jobs(s)
        s.run_loop()
    """
    scheduler.add_job(
        nightly_agile_sprint,
        trigger="cron",
        hour=2,
        minute=0,
        id="nightly-agile-sprint",
        misfire_grace_time=600,
    )

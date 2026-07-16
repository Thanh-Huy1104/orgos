"""Parse HEARTBEAT.md natural-language schedules into asyncio-friendly ticks.

Supported schedule syntax (case-insensitive, in markdown ## headers):

    ## Every N seconds
    ## Every N minutes
    ## Every N hours

Prose under each header is the "action text" that the agent's runtime
interprets (typically it names a Python function to call — the runtime
matches by keyword).

More sophisticated schedules (cron syntax, times of day) are deferred.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class ScheduledTask:
    name: str                 # header without the "Every N …" prefix, if any
    cadence_seconds: int
    action_text: str
    _last_fired_at: float = field(default=-1.0, repr=False)


_HEADER_RE = re.compile(
    r"^\s*##\s*Every\s+(\d+)\s*(seconds?|minutes?|hours?)\b",
    re.IGNORECASE | re.MULTILINE,
)


def _to_seconds(n: int, unit: str) -> int:
    unit = unit.lower().rstrip("s")
    if unit == "second":
        return n
    if unit == "minute":
        return n * 60
    if unit == "hour":
        return n * 3600
    return n  # fallback


def parse_schedule(text: str) -> list[ScheduledTask]:
    """Parse HEARTBEAT.md text → list of ScheduledTask.

    Each `## Every N unit` header starts a task; its body is everything
    until the next `## ` header or end of file.
    """
    if not text.strip():
        return []
    matches = list(_HEADER_RE.finditer(text))
    tasks: list[ScheduledTask] = []
    for i, m in enumerate(matches):
        n = int(m.group(1))
        unit = m.group(2)
        cadence = _to_seconds(n, unit)
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[body_start:body_end].strip()
        tasks.append(ScheduledTask(
            name=f"every_{n}_{unit.lower().rstrip('s')}",
            cadence_seconds=cadence,
            action_text=body,
        ))
    return tasks


class HeartbeatScheduler:
    """Track when each ScheduledTask is due to fire.

    Callers invoke `.pending(now_seconds)` on each heartbeat tick; it returns
    the tasks that are due to fire, and internally marks their last-fired time.
    """

    def __init__(self, heartbeat_md_text: str):
        self.tasks: list[ScheduledTask] = parse_schedule(heartbeat_md_text)

    def pending(self, now_seconds: float) -> list[ScheduledTask]:
        due: list[ScheduledTask] = []
        for t in self.tasks:
            if t._last_fired_at < 0 or (now_seconds - t._last_fired_at) >= t.cadence_seconds:
                due.append(t)
                t._last_fired_at = now_seconds
        return due

    def next_tick_in(self, now_seconds: float) -> float:
        """Seconds until the soonest task is next due."""
        if not self.tasks:
            return 60.0  # arbitrary default when no tasks
        soonest = min(
            (t._last_fired_at + t.cadence_seconds) - now_seconds
            for t in self.tasks
        )
        return max(0.1, soonest)

"""Framework-free result + violation types shared by every execution path.

``SpawnResult`` is returned by both the CrewAI ``spawn()`` engine and the
backend-based ``run_governed()`` runner, so consumers can switch execution
layers without changing their result handling.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .contracts import HandoffEnvelope


class TierViolation(ValueError):
    """Raised when a role's tier doesn't permit the configured tools."""


class ToolConfigurationError(RuntimeError):
    """A tool is mis-wired (e.g. an async run function on the sync boundary).

    A configuration problem the *model* cannot repair — treated as a
    governance abort by backends (never fed back as a recoverable tool
    error) so it surfaces loudly instead of degrading the run silently.
    """


@dataclass
class SpawnResult:
    envelope: HandoffEnvelope
    run_id: str
    token_usage: dict[str, int] | None
    raw_output: str | None
    tasks_output: list[Any]
    # Set by the rubric loop (spawn_until / chain_until): how many attempts ran,
    # the final grade (a GradeResult, or None when not run under a rubric), and
    # the run_id of every attempt (so a report can show all the runs it did).
    attempts: int = 1
    grade: Any = None
    attempt_run_ids: list[str] = field(default_factory=list)
    # Grades from every attempt — populated by the rubric loop so the Reflector
    # can diff failed vs successful attempts and extract heuristics.
    attempt_grades: list[Any] = field(default_factory=list)

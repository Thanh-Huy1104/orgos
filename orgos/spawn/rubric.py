"""Rubric loop — make "good enough" an explicit, gradeable object and keep
retrying until a run meets it.

The pattern, one layer above ``spawn()`` / ``spawn_chain()`` the way those sit
above CrewAI:

    state the bar as a Rubric → run the work → a *separate* grader scores the
    output → feed any failures back into the next attempt → stop when the bar is
    met or attempts run out (fail closed — never fake a pass).

Graders are registered by name so a ``Rubric`` stays YAML-serialisable: it
carries a string key, not a function, and the code-side registry resolves the
key to the real check. This is the same split the Anthropic Agent SDK uses
(rubric is data; grading is the harness). Deterministic graders (e.g. the
cointegration gates) cost nothing — loop freely; agent graders (e.g. legal
review) cost tokens — keep ``max_attempts`` low.

The grader runs in a context separate from the worker (a deterministic function,
or a *different* spawned role) — a worker never grades its own output.
"""

from __future__ import annotations

from typing import Any, Callable

from pydantic import BaseModel, Field

from .contracts import TaskBrief
from .engine import SpawnResult, spawn, spawn_chain


class GradeResult(BaseModel):
    """A grader's verdict on one run."""

    passed: bool
    failures: list[str] = Field(default_factory=list)  # fed back into the next attempt
    notes: str = ""
    grader: str = ""
    score: float = 0.0  # higher = better; lets an optimize loop keep the best attempt


class Rubric(BaseModel):
    """An explicit, YAML-serialisable definition of "good enough".

    ``grader`` names a registered grader (see ``register_grader``); unknown keys
    fall back to ``"completed"``. ``criteria`` is the human/agent-readable
    checklist (used by criteria-driven graders and as documentation).
    """

    criteria: list[str] = Field(default_factory=list)
    grader: str = "completed"
    max_attempts: int = 3
    # When True, don't stop at the first passing attempt: run all max_attempts,
    # push the grader to beat its own best, and return the highest-scoring result
    # (graded optimisation, like the Anthropic "Outcomes" rubric). Costs the full
    # attempt budget every time, so reserve it for runs where quality > latency.
    optimize: bool = False


GraderFn = Callable[[SpawnResult, Any], GradeResult]
GRADERS: dict[str, GraderFn] = {}


def register_grader(name: str) -> Callable[[GraderFn], GraderFn]:
    """Register a grader under ``name`` so a Rubric can reference it by string."""

    def deco(fn: GraderFn) -> GraderFn:
        GRADERS[name] = fn
        return fn

    return deco


@register_grader("completed")
def _grade_completed(result: SpawnResult, org: Any = None) -> GradeResult:
    """Trivial default grader: pass iff the run produced a completed envelope."""
    ok = result.envelope.status == "completed"
    return GradeResult(
        passed=ok, grader="completed",
        failures=[] if ok else [f"run status was '{result.envelope.status}', not completed"],
    )


def grade(result: SpawnResult, rubric: Rubric, *, org: Any = None) -> GradeResult:
    """Score ``result`` against ``rubric`` using the named grader."""
    fn = GRADERS.get(rubric.grader, _grade_completed)
    return fn(result, org)


# ── The loops ─────────────────────────────────────────────────────────────────

def _feedback_for(g: GradeResult, attempt: int, optimize: bool) -> list[str]:
    """The note(s) to carry into the next attempt: what to fix on a failure, or —
    when optimising past a pass — a nudge to beat the score just achieved."""
    if g.passed and optimize:
        return [f"Attempt {attempt} already met the bar (score {g.score:.2f}). Propose "
                "DIFFERENT universes/sectors to find a STRONGER result — do not re-scan "
                "the same names."]
    return [f"Do NOT repeat attempt {attempt}'s approach — it failed the rubric: {f}"
            for f in g.failures]


def _append_boundaries(brief: TaskBrief, lines: list[str]) -> TaskBrief:
    """Return a copy of ``brief`` with ``lines`` appended to its boundaries, so the
    next attempt sees exactly what to fix or beat."""
    return brief.model_copy(update={"boundaries": list(brief.boundaries) + lines})


def _exhausted(result: SpawnResult, rubric: Rubric, last_grade: GradeResult) -> SpawnResult:
    """Fail closed: a run that never met its rubric is not 'completed', and the
    deterministic grade overrides whatever the agent claimed about itself."""
    if result.envelope.status == "completed":
        result.envelope.status = "needs_revision"
    result.envelope.success_criteria_met = False
    tail = (f"[rubric '{rubric.grader}' not met after {rubric.max_attempts} "
            f"attempt(s): {last_grade.failures}]")
    result.envelope.notes = ((result.envelope.notes or "") + " " + tail).strip()
    return result


def spawn_until(
    role: Any, brief: TaskBrief, rubric: Rubric, *, org: Any = None, **spawn_kw: Any,
) -> SpawnResult:
    """Spawn ``role`` on ``brief`` repeatedly until it passes ``rubric``.

    Re-injects each attempt's failures into the next brief. Returns the passing
    result, or — when attempts run out — the last result marked needs_revision
    with the failures in its notes. If the grader itself raises (e.g. nothing to
    grade), the underlying result is trusted and returned without looping.
    """
    result = last_grade = None
    best: tuple[SpawnResult, GradeResult] | None = None
    ran_ids: list[str] = []
    for attempt in range(1, max(1, rubric.max_attempts) + 1):
        result = spawn(role, brief, **spawn_kw)
        result.attempts = attempt
        if getattr(result, "run_id", None):
            ran_ids.append(result.run_id)
        try:
            last_grade = grade(result, rubric, org=org)
        except Exception:  # noqa: BLE001 — ungradeable → trust the result, don't loop
            result.attempt_run_ids = ran_ids
            return result
        result.grade = last_grade
        if last_grade.passed:
            result.envelope.success_criteria_met = True
            if not rubric.optimize:
                result.attempt_run_ids = ran_ids
                return result
            if best is None or last_grade.score > best[1].score:
                best = (result, last_grade)
        brief = _append_boundaries(brief, _feedback_for(last_grade, attempt, rubric.optimize))
    chosen = best[0] if best is not None else result
    chosen.attempts = attempt  # total attempts run
    chosen.attempt_run_ids = ran_ids
    return chosen if best is not None else _exhausted(result, rubric, last_grade)


def chain_until(
    steps: list[tuple[Any, TaskBrief]], rubric: Rubric, *, org: Any = None,
    feedback_into: int = 0, runner: Callable[..., SpawnResult] = spawn_chain,
    **chain_kw: Any,
) -> SpawnResult:
    """Run a ``spawn_chain`` repeatedly until it passes ``rubric``.

    ``feedback_into`` is the index of the step whose brief receives the prior
    attempt's failures (default 0 — the first step, e.g. push a "no pair
    survived" failure back to the researcher to re-aim). ``runner`` is injectable
    so callers/tests can supply their own chain runner.
    """
    steps = list(steps)
    result = last_grade = None
    best: tuple[SpawnResult, GradeResult] | None = None
    ran_ids: list[str] = []
    for attempt in range(1, max(1, rubric.max_attempts) + 1):
        result = runner(steps, **chain_kw)
        result.attempts = attempt
        if getattr(result, "run_id", None):
            ran_ids.append(result.run_id)
        try:
            last_grade = grade(result, rubric, org=org)
        except Exception:  # noqa: BLE001 — ungradeable → trust the result, don't loop
            result.attempt_run_ids = ran_ids
            return result
        result.grade = last_grade
        if last_grade.passed:
            result.envelope.success_criteria_met = True
            if not rubric.optimize:
                result.attempt_run_ids = ran_ids
                return result
            if best is None or last_grade.score > best[1].score:
                best = (result, last_grade)
        i = feedback_into % len(steps)
        role_i, brief_i = steps[i]
        steps[i] = (role_i, _append_boundaries(
            brief_i, _feedback_for(last_grade, attempt, rubric.optimize)))
    chosen = best[0] if best is not None else result
    chosen.attempts = attempt  # total attempts run
    chosen.attempt_run_ids = ran_ids
    return chosen if best is not None else _exhausted(result, rubric, last_grade)

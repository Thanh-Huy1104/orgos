"""Tests for the rubric loop — grade dispatch, spawn_until / chain_until, and
the fail-closed + feedback-injection behaviour. No LLM required: spawn is
mocked, graders are deterministic."""

from agentkit.governance import HandoffEnvelope, SpawnResult
from agentkit.governance import rubric as rb
from agentkit.governance.rubric import (
    GradeResult,
    Rubric,
    chain_until,
    grade,
    register_grader,
    spawn_until,
)


def _result(status="completed", run_id="r1"):
    return SpawnResult(
        envelope=HandoffEnvelope(role="x", status=status, summary="s"),
        run_id=run_id, token_usage=None, raw_output=None, tasks_output=[],
    )


# ── Grade dispatch ────────────────────────────────────────────────────────────


class TestGradeDispatch:
    def test_completed_grader_passes_on_completed(self):
        g = grade(_result("completed"), Rubric(grader="completed"))
        assert g.passed

    def test_completed_grader_fails_otherwise(self):
        g = grade(_result("failed"), Rubric(grader="completed"))
        assert not g.passed and g.failures

    def test_unknown_grader_falls_back_to_completed(self):
        g = grade(_result("completed"), Rubric(grader="does-not-exist"))
        assert g.passed  # fell back to "completed"

    def test_register_grader_roundtrip(self):
        @register_grader("always-fail-test")
        def _g(result, org=None):
            return GradeResult(passed=False, failures=["nope"], grader="always-fail-test")
        assert grade(_result(), Rubric(grader="always-fail-test")).failures == ["nope"]


# ── spawn_until ───────────────────────────────────────────────────────────────


class TestSpawnUntil:
    def test_passes_first_try_no_retry(self, monkeypatch):
        calls = {"n": 0}
        monkeypatch.setattr(rb, "spawn", lambda role, brief, **k: (calls.__setitem__("n", calls["n"] + 1) or _result("completed")))
        out = spawn_until("role", _brief(), Rubric(grader="completed", max_attempts=3))
        assert calls["n"] == 1
        assert out.envelope.success_criteria_met is True

    def test_retries_then_fails_closed(self, monkeypatch):
        calls = {"n": 0}

        def fake_spawn(role, brief, **k):
            calls["n"] += 1
            calls["last_brief"] = brief
            return _result("completed")  # completes, but the rubric grader rejects it

        monkeypatch.setattr(rb, "spawn", fake_spawn)
        out = spawn_until("role", _brief(), Rubric(grader="always-fail-test", max_attempts=3))
        assert calls["n"] == 3                          # exhausted all attempts
        assert out.envelope.status == "needs_revision"  # fail closed, not "completed"
        assert out.envelope.success_criteria_met is False  # grade overrides self-report
        assert "always-fail-test" in (out.envelope.notes or "")
        # failures were injected into later attempts' briefs
        assert any("failed the rubric" in b for b in calls["last_brief"].boundaries)

    def test_ungradeable_result_returned_without_loop(self, monkeypatch):
        calls = {"n": 0}

        def boom(result, org=None):
            raise RuntimeError("nothing to grade")

        register_grader("boom-test")(boom)
        monkeypatch.setattr(rb, "spawn", lambda role, brief, **k: (calls.__setitem__("n", calls["n"] + 1) or _result("completed")))
        out = spawn_until("role", _brief(), Rubric(grader="boom-test", max_attempts=3))
        assert calls["n"] == 1                       # did not loop
        assert out.envelope.status == "completed"    # left untouched


# ── chain_until ───────────────────────────────────────────────────────────────


class TestChainUntil:
    def test_injects_feedback_into_chosen_step(self):
        seen = {"briefs": []}

        def runner(steps, **kw):
            seen["briefs"].append(steps[0][1])  # researcher brief each attempt
            return _result("completed")

        out = chain_until(
            [("researcher", _brief()), ("scanner", _brief())],
            Rubric(grader="always-fail-test", max_attempts=2),
            runner=runner, feedback_into=0,
        )
        assert len(seen["briefs"]) == 2
        # second attempt's researcher brief carries the first attempt's failure
        assert any("failed the rubric" in b for b in seen["briefs"][1].boundaries)
        assert out.envelope.status == "needs_revision"


class TestOptimizeLoop:
    def test_runs_all_attempts_and_keeps_best(self):
        # grader passes every time with an increasing score; optimize should run
        # all attempts (not stop at the first pass) and return the best-scoring one.
        scores = iter([0.3, 0.9, 0.5])
        returned = []

        def runner(steps, **kw):
            r = _result("completed", run_id=f"r{len(returned)}")
            returned.append(r)
            return r

        def grader(result, org=None):
            return GradeResult(passed=True, grader="opt-test", score=next(scores))

        register_grader("opt-test")(grader)
        out = chain_until(
            [("a", _brief())],
            Rubric(grader="opt-test", max_attempts=3, optimize=True),
            runner=runner,
        )
        assert len(returned) == 3            # did not stop at first pass
        assert out is returned[1]            # kept the 0.9 attempt
        assert out.envelope.success_criteria_met is True
        # every attempt's run_id is recorded on the kept result
        assert out.attempt_run_ids == ["r0", "r1", "r2"]
        assert out.attempts == 3

    def test_optimize_off_stops_at_first_pass(self):
        calls = {"n": 0}

        def runner(steps, **kw):
            calls["n"] += 1
            return _result("completed")

        def grader(result, org=None):
            return GradeResult(passed=True, grader="opt-test2", score=0.1)

        register_grader("opt-test2")(grader)
        chain_until([("a", _brief())], Rubric(grader="opt-test2", max_attempts=3),
                    runner=runner)
        assert calls["n"] == 1               # default optimize=False → early return


def _brief():
    from agentkit.governance import TaskBrief
    return TaskBrief(objective="A concrete, actionable objective for testing.")

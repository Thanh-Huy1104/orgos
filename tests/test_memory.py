"""Tests for orgos.memory — OrgMemory, OwnerProfile, context injection.

No LLM key required — tests the storage engine and query API directly.
"""

import json
import tempfile
from pathlib import Path

import pytest

from orgos import HandoffEnvelope, TaskBrief
from orgos.memory import OrgMemory, OwnerProfile


@pytest.fixture
def memory():
    """Fresh in-memory SQLite store for each test."""
    db = tempfile.mktemp(suffix=".db")
    m = OrgMemory(db)
    yield m
    m.close()
    Path(db).unlink(missing_ok=True)


@pytest.fixture
def envelope():
    return HandoffEnvelope(
        role="test-role",
        status="completed",
        summary="Test run completed successfully.",
        success_criteria_met=True,
        payload=json.dumps({"key": "value"}),
    )


@pytest.fixture
def brief():
    return TaskBrief(objective="Run a test scan.")


# ── Run recording ─────────────────────────────────────────────────────────


class TestRunRecording:
    def test_record_and_retrieve_last(self, memory, envelope, brief):
        rid = memory.record_run("finance", "test-role", envelope, brief, {"total_tokens": 100})
        last = memory.last_run(department="finance")
        assert last is not None
        assert last.id == rid
        assert last.role == "test-role"
        assert last.status == "completed"
        assert last.total_tokens == 100

    def test_record_multiple_runs(self, memory, envelope, brief):
        memory.record_run("finance", "scanner", envelope, brief, {"total_tokens": 100})
        memory.record_run("finance", "validator", envelope, brief, {"total_tokens": 200})
        memory.record_run("legal", "reviewer", envelope, brief, {"total_tokens": 50})

        recent_finance = memory.recent_runs(department="finance", limit=10)
        assert len(recent_finance) == 2

        recent_legal = memory.recent_runs(department="legal", limit=10)
        assert len(recent_legal) == 1

    def test_recent_runs_respects_limit(self, memory, envelope, brief):
        for i in range(5):
            memory.record_run("finance", f"role-{i}", envelope, brief, {"total_tokens": 10})
        assert len(memory.recent_runs(limit=3)) == 3

    def test_last_run_none_for_empty(self, memory):
        assert memory.last_run(department="nonexistent") is None

    def test_recorded_payload_is_json(self, memory, envelope, brief):
        memory.record_run("finance", "test", envelope, brief, None)
        last = memory.last_run(department="finance")
        assert last is not None
        parsed = json.loads(last.payload)
        assert parsed == {"key": "value"}


# ── Decisions ──────────────────────────────────────────────────────────────


class TestDecisions:
    def test_record_and_query_decision(self, memory):
        memory.record_decision(
            role="publisher",
            decision_type="approval",
            summary="Deploy to production",
            tool="DeployTool",
            owner_response="approved",
        )
        approvals = memory.recent_approvals(days=30)
        assert len(approvals) == 1
        assert approvals[0].type == "approval"
        assert approvals[0].role == "publisher"
        assert approvals[0].owner_response == "approved"

    def test_decision_linked_to_run(self, memory, envelope, brief):
        rid = memory.record_run("finance", "test", envelope, brief, None)
        memory.record_decision(
            run_id=rid,
            role="test",
            decision_type="escalation",
            summary="Needs human review",
        )
        approvals = memory.recent_approvals()
        assert len(approvals) == 1
        assert approvals[0].run_id == rid


# ── Preferences ────────────────────────────────────────────────────────────


class TestPreferences:
    def test_set_and_get(self, memory):
        memory.set_preference("theme", "dark")
        assert memory.get_preference("theme") == "dark"

    def test_get_missing_default(self, memory):
        assert memory.get_preference("nonexistent", "fallback") == "fallback"

    def test_json_values(self, memory):
        memory.set_preference("limits", {"daily": 1000, "weekly": 5000})
        val = memory.get_preference("limits")
        assert val == {"daily": 1000, "weekly": 5000}

    def test_overwrite(self, memory):
        memory.set_preference("key", "v1")
        memory.set_preference("key", "v2")
        assert memory.get_preference("key") == "v2"


# ── Department spend ───────────────────────────────────────────────────────


class TestDepartmentSpend:
    def test_aggregates_tokens(self, memory, envelope, brief):
        memory.record_run("finance", "r1", envelope, brief, {"total_tokens": 100, "prompt_tokens": 60, "completion_tokens": 40})
        memory.record_run("finance", "r2", envelope, brief, {"total_tokens": 200, "prompt_tokens": 120, "completion_tokens": 80})

        spend = memory.department_spend("finance", days=30)
        assert spend["total_tokens"] == 300
        assert spend["prompt_tokens"] == 180
        assert spend["completion_tokens"] == 120
        assert spend["runs"] == 2

    def test_empty_department(self, memory):
        spend = memory.department_spend("nonexistent", days=30)
        assert spend["total_tokens"] == 0
        assert spend["runs"] == 0


# ── Search ─────────────────────────────────────────────────────────────────


class TestSearch:
    def test_search_objective(self, memory, envelope, brief):
        b = TaskBrief(objective="Find cointegrated pairs in SPY and QQQ.")
        memory.record_run("finance", "scanner", envelope, b, None)
        results = memory.search_runs("cointegrated")
        assert len(results) == 1
        assert "SPY" in results[0].objective

    def test_search_summary(self, memory, envelope, brief):
        env = HandoffEnvelope(
            role="test", status="completed",
            summary="Found 3 cointegrated pairs. All verified.",
            success_criteria_met=True,
        )
        memory.record_run("finance", "validator", env, brief, None)
        results = memory.search_runs("verified")
        assert len(results) == 1

    def test_search_no_match(self, memory):
        assert memory.search_runs("zzz_nonexistent") == []


# ── Context injection ──────────────────────────────────────────────────────


class TestContextInjection:
    def test_includes_owner_preferences(self, memory):
        owner = OwnerProfile(name="Alice", preferences="Be thorough.")
        ctx = memory.context_for(owner=owner)
        assert "Alice" in ctx
        assert "Be thorough" in ctx

    def test_includes_owner_feedback(self, memory):
        owner = OwnerProfile(
            name="Bob",
            feedback=["Reject half-life > 30 days.", "Always test all pairs."],
        )
        ctx = memory.context_for(owner=owner)
        assert "half-life > 30 days" in ctx
        assert "test all pairs" in ctx

    def test_includes_recent_runs(self, memory, envelope, brief):
        memory.record_run("finance", "scanner", envelope, brief, {"total_tokens": 100})
        ctx = memory.context_for(department="finance")
        assert "Recent activity" in ctx
        assert "scanner" in ctx

    def test_includes_token_spend(self, memory, envelope, brief):
        memory.record_run("finance", "r1", envelope, brief, {"total_tokens": 500})
        ctx = memory.context_for(department="finance")
        assert "Token usage" in ctx
        assert "500" in ctx

    def test_warns_on_failed_last_run(self, memory, brief):
        env = HandoffEnvelope(
            role="test", status="failed",
            summary="Something went wrong.",
            success_criteria_met=False,
        )
        memory.record_run("finance", "test", env, brief, None)
        ctx = memory.context_for(department="finance")
        assert "not completed" in ctx.lower() or "⚠" in ctx


# ── OwnerProfile rendering ──────────────────────────────────────────────────


class TestOwnerProfile:
    def test_to_context_block(self):
        owner = OwnerProfile(
            name="Carol",
            preferences="Conservative.",
            feedback=["Prefer short answers."],
        )
        block = owner.to_context_block()
        assert "Carol" in block
        assert "Conservative" in block
        assert "short answers" in block

    def test_truncates_feedback_to_last_5(self):
        owner = OwnerProfile(feedback=[f"Feedback {i}" for i in range(10)])
        block = owner.to_context_block()
        # Only last 5 should appear
        assert "Feedback 9" in block
        assert "Feedback 0" not in block

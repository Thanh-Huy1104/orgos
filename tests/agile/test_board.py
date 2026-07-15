"""Tests for the board READY gate logic (Plan 3)."""

from __future__ import annotations

import pytest

from orgos.agile.board import (
    MAX_FILES,
    MAX_LOC,
    REQUIRED_ROLES,
    ReadyGateResult,
    check_ready_gate,
    story_fits_size_caps,
)


class TestConstants:
    def test_size_caps_are_reasonable(self):
        assert MAX_FILES == 5
        assert MAX_LOC == 400

    def test_required_roles_are_the_three_delivery_workers(self):
        assert set(REQUIRED_ROLES) == {"architect", "test", "devsecops"}


class TestStoryFitsSizeCaps:
    def test_within_caps(self):
        ok, reason = story_fits_size_caps(3, 200)
        assert ok
        assert "within caps" in reason

    def test_exceeds_files(self):
        ok, reason = story_fits_size_caps(6, 100)
        assert not ok
        assert "files" in reason

    def test_exceeds_loc(self):
        ok, reason = story_fits_size_caps(3, 500)
        assert not ok
        assert "LOC" in reason

    def test_exceeds_both(self):
        ok, reason = story_fits_size_caps(7, 500)
        assert not ok
        assert "files" in reason
        assert "LOC" in reason

    def test_at_boundary_is_ok(self):
        ok, _ = story_fits_size_caps(5, 400)
        assert ok


class TestCheckReadyGate:
    def test_ready_when_all_signed_and_in_caps(self):
        r = check_ready_gate(
            title="Fix login",
            acceptance_criteria=["Users can log in"],
            estimated_files=3,
            estimated_loc=200,
            role_signoffs={"architect": True, "test": True, "devsecops": True},
        )
        assert r.ready
        assert r.missing_signoffs == []
        assert r.size_failures == []
        assert "ready" in r.reason

    def test_missing_signoffs_blocks_ready(self):
        r = check_ready_gate(
            title="Fix login",
            acceptance_criteria=["Users can log in"],
            estimated_files=2,
            estimated_loc=100,
            role_signoffs={"architect": True},
        )
        assert not r.ready
        assert "test" in r.missing_signoffs
        assert "devsecops" in r.missing_signoffs

    def test_no_signoffs_at_all(self):
        r = check_ready_gate(
            title="Fix login",
            acceptance_criteria=["Users can log in"],
            estimated_files=2,
            estimated_loc=100,
        )
        assert not r.ready
        assert len(r.missing_signoffs) == 3

    def test_size_cap_blocks_ready(self):
        r = check_ready_gate(
            title="Huge refactor",
            acceptance_criteria=["Tests pass"],
            estimated_files=10,
            estimated_loc=1000,
            role_signoffs={"architect": True, "test": True, "devsecops": True},
        )
        assert not r.ready
        assert len(r.size_failures) == 2

    def test_empty_title_blocks_ready(self):
        r = check_ready_gate(
            title="",
            acceptance_criteria=["AC"],
            estimated_files=1,
            estimated_loc=50,
            role_signoffs={"architect": True, "test": True, "devsecops": True},
        )
        assert not r.ready
        assert "no title" in r.reason

    def test_empty_acceptance_criteria_blocks_ready(self):
        r = check_ready_gate(
            title="Fix login",
            estimated_files=1,
            estimated_loc=50,
            role_signoffs={"architect": True, "test": True, "devsecops": True},
        )
        assert not r.ready
        assert "acceptance criteria" in r.reason

    def test_false_signoff_counts(self):
        r = check_ready_gate(
            title="Fix login",
            acceptance_criteria=["AC"],
            estimated_files=2,
            estimated_loc=100,
            role_signoffs={"architect": True, "test": False, "devsecops": True},
        )
        assert not r.ready
        assert "test" in r.missing_signoffs

    def test_extra_signoffs_ignored(self):
        r = check_ready_gate(
            title="Fix login",
            acceptance_criteria=["AC"],
            estimated_files=2,
            estimated_loc=100,
            role_signoffs={
                "architect": True, "test": True, "devsecops": True,
                "product_owner": True,
            },
        )
        assert r.ready

    def test_ready_gate_result_is_a_dataclass(self):
        r = check_ready_gate(title="T", acceptance_criteria=["AC"])
        assert isinstance(r, ReadyGateResult)
        assert hasattr(r, "ready")
        assert hasattr(r, "missing_signoffs")
        assert hasattr(r, "size_failures")
        assert hasattr(r, "reason")

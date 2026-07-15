"""Tests for SwapTopology mutation (Plan 5)."""

from __future__ import annotations

import pytest

from orgos.agile.mutations import (
    SwapTopology,
    apply_mutation,
)


class TestSwapTopology:
    def test_creates_mutation(self):
        m = SwapTopology(agents_dir="agents_alt")
        assert m.agents_dir == "agents_alt"
        assert m.kind == "swap_topology"

    def test_apply_sets_agents_dir_in_snapshot(self):
        snapshot = {
            "sprint_id": "s1",
            "picked_issue": {"issue_id": "42"},
            "backlog": [],
        }
        m = SwapTopology(agents_dir="agents_experiment")
        mutated = apply_mutation(snapshot, m)
        assert mutated["agents_dir"] == "agents_experiment"
        assert mutated["sprint_id"] == "s1"  # original preserved
        assert mutated["picked_issue"]["issue_id"] == "42"

    def test_apply_is_immutable(self):
        snapshot = {"key": "value"}
        m = SwapTopology(agents_dir="alt")
        mutated = apply_mutation(snapshot, m)
        assert snapshot.get("agents_dir") is None
        assert mutated["agents_dir"] == "alt"

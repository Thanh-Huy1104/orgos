"""Tests for §D1 team-level adaptation loop."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from orgos.agile.team_adaptation import (
    AdaptationProposal, AdaptiveParameters, SprintSignal,
    _BOUNDS, apply_proposals, load_or_init,
    propose_adaptations, run_adaptation_pass,
)


class TestAdaptiveParameters:
    def test_defaults(self):
        p = AdaptiveParameters()
        assert p.velocity_target == 6
        assert p.max_ac_retries == 3
        assert p.sprint_duration_seconds == 1200
        assert p.version == 1

    def test_serialize_roundtrip(self):
        p = AdaptiveParameters(velocity_target=12, max_ac_retries=5)
        d = p.to_dict()
        r = AdaptiveParameters.from_dict(d)
        assert r.velocity_target == 12
        assert r.max_ac_retries == 5

    def test_from_dict_ignores_unknown_keys(self):
        p = AdaptiveParameters.from_dict({"velocity_target": 8, "junk_field": 99})
        assert p.velocity_target == 8


class TestProposalClamp:
    def test_below_lower_bound_clamped(self):
        p = AdaptationProposal("velocity_target", 6, 1, "aggressive drop").clamp()
        assert p.new_value == _BOUNDS["velocity_target"][0]

    def test_above_upper_bound_clamped(self):
        p = AdaptationProposal("velocity_target", 30, 100, "overzealous").clamp()
        assert p.new_value == _BOUNDS["velocity_target"][1]

    def test_within_bounds_unchanged(self):
        p = AdaptationProposal("velocity_target", 10, 12, "modest").clamp()
        assert p.new_value == 12
        assert "clamped" not in p.reason


class TestProposeVelocity:
    def test_over_delivery_raises(self):
        signals = [
            SprintSignal(1, committed=6, done=7, duration_hours=0.3, end_reason="story_cap"),
            SprintSignal(2, committed=6, done=8, duration_hours=0.2, end_reason="story_cap"),
        ]
        current = AdaptiveParameters(velocity_target=6)
        props = propose_adaptations(signals, current)
        vt = [p for p in props if p.field == "velocity_target"]
        assert vt and vt[0].new_value > 6

    def test_under_delivery_lowers(self):
        signals = [
            SprintSignal(1, committed=10, done=2, duration_hours=0.3, end_reason="scheduled"),
            SprintSignal(2, committed=10, done=3, duration_hours=0.3, end_reason="scheduled"),
        ]
        current = AdaptiveParameters(velocity_target=10)
        props = propose_adaptations(signals, current)
        vt = [p for p in props if p.field == "velocity_target"]
        assert vt and vt[0].new_value < 10

    def test_balanced_no_change(self):
        signals = [
            SprintSignal(1, committed=6, done=4, duration_hours=0.3, end_reason="scheduled"),
            SprintSignal(2, committed=6, done=5, duration_hours=0.3, end_reason="scheduled"),
        ]
        current = AdaptiveParameters(velocity_target=6)
        props = propose_adaptations(signals, current)
        vt = [p for p in props if p.field == "velocity_target"]
        assert not vt


class TestProposeMaxACRetries:
    def test_high_success_rate_raises_cap(self):
        signals = [
            SprintSignal(1, committed=6, done=4, duration_hours=0.3, end_reason="scheduled",
                         ac_retries_started=5, ac_retries_succeeded=4),
        ]
        current = AdaptiveParameters(max_ac_retries=3)
        props = propose_adaptations(signals, current)
        r = [p for p in props if p.field == "max_ac_retries"]
        assert r and r[0].new_value == 4

    def test_low_success_rate_lowers_cap(self):
        signals = [
            SprintSignal(1, committed=6, done=4, duration_hours=0.3, end_reason="scheduled",
                         ac_retries_started=10, ac_retries_succeeded=1),
        ]
        current = AdaptiveParameters(max_ac_retries=3)
        props = propose_adaptations(signals, current)
        r = [p for p in props if p.field == "max_ac_retries"]
        assert r and r[0].new_value == 2

    def test_too_few_samples_no_change(self):
        signals = [
            SprintSignal(1, committed=6, done=4, duration_hours=0.3, end_reason="scheduled",
                         ac_retries_started=1, ac_retries_succeeded=1),
        ]
        current = AdaptiveParameters(max_ac_retries=3)
        props = propose_adaptations(signals, current)
        r = [p for p in props if p.field == "max_ac_retries"]
        assert not r


class TestProposeSprintDuration:
    def test_repeated_story_cap_lengthens_sprint(self):
        signals = [
            SprintSignal(1, 6, 6, 0.05, "story_cap"),
            SprintSignal(2, 6, 6, 0.05, "story_cap"),
        ]
        current = AdaptiveParameters(sprint_duration_seconds=1200)
        props = propose_adaptations(signals, current)
        d = [p for p in props if p.field == "sprint_duration_seconds"]
        assert d and d[0].new_value > 1200

    def test_repeated_scheduled_underdel_shortens_sprint(self):
        signals = [
            SprintSignal(1, 10, 2, 0.5, "scheduled"),
            SprintSignal(2, 10, 3, 0.5, "scheduled"),
        ]
        current = AdaptiveParameters(sprint_duration_seconds=1200)
        props = propose_adaptations(signals, current)
        d = [p for p in props if p.field == "sprint_duration_seconds"]
        assert d and d[0].new_value < 1200


class TestApplyProposals:
    def test_apply_updates_workspace_and_disk(self, tmp_path):
        ws = MagicMock()
        ws.root = tmp_path

        proposals = [
            AdaptationProposal("velocity_target", 6, 12, "raise"),
            AdaptationProposal("max_ac_retries", 3, 5, "raise"),
        ]
        updated = apply_proposals(ws, proposals, emitter=None)
        assert updated.velocity_target == 12
        assert updated.max_ac_retries == 5
        # Persisted to disk
        assert (tmp_path / "adaptation.json").exists()

    def test_apply_emits_events(self, tmp_path):
        ws = MagicMock()
        ws.root = tmp_path
        emitter = MagicMock()
        proposals = [AdaptationProposal("velocity_target", 6, 8, "raise")]
        apply_proposals(ws, proposals, emitter=emitter)
        emitter.emit.assert_called_once()
        assert emitter.emit.call_args.args[0] == "team_adapted"

    def test_empty_proposals_no_op(self, tmp_path):
        ws = MagicMock()
        ws.root = tmp_path
        emitter = MagicMock()
        updated = apply_proposals(ws, [], emitter=emitter)
        assert updated.velocity_target == 6  # unchanged default
        emitter.emit.assert_not_called()


class TestLoadOrInit:
    def test_defaults_when_no_file(self, tmp_path):
        ws = MagicMock()
        ws.root = tmp_path
        # ensure ws.adaptive_params doesn't auto-satisfy the check
        del ws.adaptive_params  # MagicMock hack
        # After deletion, subsequent access re-creates a Mock — but our
        # isinstance check filters that. Let's just use a real object.
        class Bag:
            pass
        real_ws = Bag()
        real_ws.root = tmp_path
        p = load_or_init(real_ws)
        assert p.velocity_target == 6
        assert real_ws.adaptive_params is p

    def test_reads_from_disk(self, tmp_path):
        import json
        (tmp_path / "adaptation.json").write_text(json.dumps({
            "velocity_target": 14, "max_ac_retries": 5,
            "sprint_duration_seconds": 900, "version": 3,
        }))
        class Bag:
            pass
        ws = Bag()
        ws.root = tmp_path
        p = load_or_init(ws)
        assert p.velocity_target == 14
        assert p.max_ac_retries == 5
        assert p.version == 3

    def test_magicmock_doesnt_pollute(self, tmp_path):
        """Regression: MagicMock's autospec truthy attribute broke the
        cache-check before we added the isinstance filter."""
        ws = MagicMock()
        ws.root = tmp_path
        # ws.adaptive_params is a MagicMock, but load_or_init should
        # NOT return it — should return real AdaptiveParameters
        p = load_or_init(ws)
        assert isinstance(p, AdaptiveParameters)

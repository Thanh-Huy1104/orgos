"""Tests for planning poker helpers — coercion + divergence detection."""

from __future__ import annotations

from orgos.agile.poker import FIB, _coerce_points, discussion_needed


class TestCoercePoints:
    def test_valid_fib_passes_through(self):
        for v in FIB:
            assert _coerce_points(v) == v

    def test_non_fib_snaps_to_nearest(self):
        assert _coerce_points(4) == 3   # closer to 3 than 5
        assert _coerce_points(6) == 5   # closer to 5 than 8
        assert _coerce_points(10) == 8
        assert _coerce_points(20) == 13
        assert _coerce_points(0) == 1

    def test_string_int_coerces(self):
        assert _coerce_points("5") == 5
        assert _coerce_points("4") == 3

    def test_non_numeric_returns_none(self):
        assert _coerce_points(None) is None
        assert _coerce_points("?") is None
        assert _coerce_points("not a number") is None


class TestDiscussionNeeded:
    def test_empty_no_discussion(self):
        assert not discussion_needed([])

    def test_single_vote_no_discussion(self):
        assert not discussion_needed([{"voter": "a", "points": 3}])

    def test_all_same_no_discussion(self):
        votes = [{"voter": r, "points": 3} for r in ("a", "b", "c")]
        assert not discussion_needed(votes)

    def test_adjacent_no_discussion(self):
        # 2 and 5 are 2 Fibonacci steps apart (indices 1, 3 → diff 2)
        votes = [{"voter": "a", "points": 2}, {"voter": "b", "points": 5}]
        assert not discussion_needed(votes)

    def test_far_apart_triggers_discussion(self):
        # 1 and 13 are 5 steps apart
        votes = [{"voter": "a", "points": 1}, {"voter": "b", "points": 13}]
        assert discussion_needed(votes)

    def test_medium_gap_triggers(self):
        # 1 and 8 = 4 steps apart (indices 0, 4)
        votes = [{"voter": "a", "points": 1}, {"voter": "b", "points": 8}]
        assert discussion_needed(votes)

    def test_2_vs_8_triggers(self):
        # 2 (idx 1) and 8 (idx 4) → 3 steps > 2 triggers
        votes = [{"voter": "a", "points": 2}, {"voter": "b", "points": 8}]
        assert discussion_needed(votes)

    def test_3_vs_8_no_trigger(self):
        # 3 (idx 2) and 8 (idx 4) → exactly 2 steps, boundary case
        votes = [{"voter": "a", "points": 3}, {"voter": "b", "points": 8}]
        assert not discussion_needed(votes)

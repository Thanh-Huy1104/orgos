"""Tests for the budget governor (Fix §A5)."""

from __future__ import annotations

from orgos.agile.budget import (
    BudgetTracker, BudgetSnapshot,
    set_active_tracker, get_active_tracker, charge_if_active,
)


class TestBudgetTracker:
    def test_no_cap_never_exhausts(self):
        t = BudgetTracker(max_usd=None, model_default="deepseek/deepseek-chat")
        for _ in range(100):
            t.charge(10_000, 10_000)
        snap = t.snapshot()
        assert snap.exhausted is False
        assert snap.spent_usd > 0

    def test_cap_of_1_dollar_exhausts_eventually(self):
        exhausted_calls: list = []
        t = BudgetTracker(
            max_usd=0.01, model_default="deepseek/deepseek-chat",
            on_exhausted=lambda snap: exhausted_calls.append(snap),
        )
        # DeepSeek chat: ~$0.27/M input, $1.10/M output.
        # 1M input tokens = $0.27 → well over $0.01 cap.
        t.charge(1_000_000, 0)
        assert t.is_exhausted()
        assert len(exhausted_calls) == 1
        assert exhausted_calls[0].spent_usd > 0.01

    def test_warning_fires_at_80_pct(self):
        warns: list = []
        t = BudgetTracker(
            max_usd=1.00, model_default="deepseek/deepseek-chat",
            on_warning=lambda snap: warns.append(snap),
        )
        # ~$0.85 = 85% of $1.00 — deep enough past 80% for the latch.
        t.charge(3_000_000, 100_000)  # 3M input × $0.27 + 100k out × $1.10 = $0.92
        assert len(warns) == 1

    def test_callbacks_fire_only_once(self):
        warns: list = []
        exhaust: list = []
        t = BudgetTracker(
            max_usd=0.01, model_default="deepseek/deepseek-chat",
            on_warning=lambda s: warns.append(s),
            on_exhausted=lambda s: exhaust.append(s),
        )
        # Blow past both thresholds many times
        for _ in range(5):
            t.charge(500_000, 0)
        assert len(warns) == 1
        assert len(exhaust) == 1

    def test_snapshot_line_readable(self):
        t = BudgetTracker(max_usd=1.00, model_default="deepseek/deepseek-chat")
        t.charge(100_000, 10_000)
        line = t.snapshot().as_line()
        assert "$" in line and "/" in line and "%" in line
        assert "tokens:" in line


class TestActiveTracker:
    def test_set_and_get(self):
        set_active_tracker(None)
        assert get_active_tracker() is None
        t = BudgetTracker(max_usd=None, model_default="deepseek/deepseek-chat")
        set_active_tracker(t)
        assert get_active_tracker() is t
        set_active_tracker(None)
        assert get_active_tracker() is None

    def test_charge_if_active_no_op_when_none(self):
        set_active_tracker(None)
        # Should not raise
        charge_if_active(1000, 100, "deepseek/deepseek-chat")

    def test_charge_if_active_delegates(self):
        t = BudgetTracker(max_usd=None, model_default="deepseek/deepseek-chat")
        set_active_tracker(t)
        try:
            charge_if_active(1000, 100)
            assert t.snapshot().tokens_input == 1000
            assert t.snapshot().tokens_output == 100
        finally:
            set_active_tracker(None)

"""Cost budget governor (Fix §A5).

Adopters won't trust a runtime that can burn arbitrary $. `--max-usd N`
on `orgos start` caps the run's total spend across all executor calls
(delivery + PO + SM + ceremonies).

Design:
  - Singleton BudgetTracker per team, mutated by every executor result.
  - Emits `budget_warning` at 80% and `budget_exhausted` at 100%.
  - On exhaustion, calls the shutdown callback (usually supervisor.stop),
    which lets in-flight stories finish and then exits cleanly.
  - Never crashes the agent loop — a tracking failure just leaves the run
    to hit --timeout-seconds instead.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from orgos.agile.pricing import cost_usd


@dataclass
class BudgetSnapshot:
    max_usd: float
    spent_usd: float
    tokens_input: int
    tokens_output: int
    percent_used: float
    exhausted: bool

    def as_line(self) -> str:
        return (
            f"${self.spent_usd:.3f} / ${self.max_usd:.2f}  "
            f"({self.percent_used:.0f}%)  "
            f"tokens: {self.tokens_input:,} in / {self.tokens_output:,} out"
            + ("  ⛔ EXHAUSTED" if self.exhausted else "")
        )


class BudgetTracker:
    """Thread-safe cumulative-cost accumulator.

    Attach one per team via `set_active_tracker(tracker)` at boot.
    Delivery agents call `.charge(tokens_in, tokens_out, model)` after
    every executor run — one call, no complex threading needed.
    """

    def __init__(
        self,
        *,
        max_usd: Optional[float],
        model_default: str,
        on_warning: Optional[Callable[[BudgetSnapshot], None]] = None,
        on_exhausted: Optional[Callable[[BudgetSnapshot], None]] = None,
    ):
        self.max_usd = float(max_usd) if max_usd and max_usd > 0 else None
        self.model_default = model_default
        self._lock = threading.Lock()
        self._tokens_input = 0
        self._tokens_output = 0
        self._spent = 0.0
        self._warned = False       # 80% one-shot latch
        self._exhausted = False    # 100% one-shot latch
        self._on_warning = on_warning
        self._on_exhausted = on_exhausted

    def charge(
        self, tokens_input: int, tokens_output: int,
        model: Optional[str] = None,
    ) -> BudgetSnapshot:
        """Record a spend event and return the new snapshot. Fires callbacks
        exactly once each at the 80%/100% thresholds."""
        m = model or self.model_default
        delta = cost_usd(m, int(tokens_input or 0), int(tokens_output or 0))
        fired_warning = False
        fired_exhausted = False
        with self._lock:
            self._tokens_input += int(tokens_input or 0)
            self._tokens_output += int(tokens_output or 0)
            self._spent += delta
            snap = self._snapshot_locked()
            if self.max_usd is not None:
                if not self._warned and snap.percent_used >= 80.0:
                    self._warned = True
                    fired_warning = True
                if not self._exhausted and snap.percent_used >= 100.0:
                    self._exhausted = True
                    fired_exhausted = True
        # Fire callbacks OUTSIDE the lock (they may call back into orgos).
        if fired_warning and self._on_warning:
            try:
                self._on_warning(snap)
            except Exception:
                pass
        if fired_exhausted and self._on_exhausted:
            try:
                self._on_exhausted(snap)
            except Exception:
                pass
        return snap

    def snapshot(self) -> BudgetSnapshot:
        with self._lock:
            return self._snapshot_locked()

    def _snapshot_locked(self) -> BudgetSnapshot:
        max_usd = self.max_usd if self.max_usd is not None else float("inf")
        percent = (self._spent / max_usd * 100.0) if self.max_usd else 0.0
        return BudgetSnapshot(
            max_usd=self.max_usd or 0.0,
            spent_usd=self._spent,
            tokens_input=self._tokens_input,
            tokens_output=self._tokens_output,
            percent_used=percent,
            exhausted=self._exhausted,
        )

    def is_exhausted(self) -> bool:
        with self._lock:
            return self._exhausted


# ── Module-level singleton (one BudgetTracker per orgos process) ─────
_active_tracker: Optional[BudgetTracker] = None
_active_lock = threading.Lock()


def set_active_tracker(tracker: Optional[BudgetTracker]) -> None:
    global _active_tracker
    with _active_lock:
        _active_tracker = tracker


def get_active_tracker() -> Optional[BudgetTracker]:
    with _active_lock:
        return _active_tracker


def charge_if_active(
    tokens_input: int, tokens_output: int,
    model: Optional[str] = None,
) -> None:
    """Convenience: charge the active tracker if one is set, no-op otherwise.

    Used by AsyncAgent so hot-path executor calls don't need a null-check
    at every site.
    """
    t = get_active_tracker()
    if t is None:
        return
    try:
        t.charge(tokens_input, tokens_output, model=model)
    except Exception:
        pass

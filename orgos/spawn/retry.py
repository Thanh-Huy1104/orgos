"""Retry policy for transient failures — exponential backoff with jitter.

For *tool-level* failures (a flaky HTTP API behind a tool, a lock held for
a moment). Provider-level retries (429/5xx on the LLM call) are the SDK's
job — the Anthropic SDK already retries those; don't stack a second layer
on top of it.

Deliberately never retried: governance aborts (BudgetExceeded,
LoopDetected, ToolBudgetExceeded, TierViolation). Those are decisions,
not weather. The runner wires this in around tool execution only, after
its gates have already run.
"""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class RetryPolicy:
    """Exponential backoff: delay = min(base * 2^attempt, max) ± jitter."""

    max_attempts: int = 3
    base_delay: float = 0.5
    max_delay: float = 30.0
    jitter: float = 0.5           # fraction of the delay randomized away
    retry_on: tuple[type[Exception], ...] = field(
        default_factory=lambda: (Exception,)
    )
    never_retry: tuple[type[Exception], ...] = ()

    def _delay(self, attempt: int) -> float:
        raw = min(self.base_delay * (2 ** attempt), self.max_delay)
        if self.jitter:
            spread = raw * self.jitter
            raw = raw - spread + random.random() * 2 * spread
        # max_delay is a hard bound — jitter varies below it, never above
        # (jitter-after-cap previously allowed sleeps up to 1.5x max_delay).
        return max(0.0, min(raw, self.max_delay))

    def _should_retry(self, exc: Exception, attempt: int) -> bool:
        if attempt + 1 >= self.max_attempts:
            return False
        if isinstance(exc, self.never_retry):
            return False
        return isinstance(exc, self.retry_on)

    def call(self, fn: Callable[[], Any]) -> Any:
        """Run ``fn`` under this policy (synchronous)."""
        for attempt in range(self.max_attempts):
            try:
                return fn()
            except Exception as exc:  # noqa: BLE001 - filtered by policy
                if not self._should_retry(exc, attempt):
                    raise
                time.sleep(self._delay(attempt))
        raise RuntimeError("unreachable")  # pragma: no cover

    async def acall(self, fn: Callable[[], Any]) -> Any:
        """Run ``fn`` under this policy (async; ``fn`` may return a coroutine)."""
        for attempt in range(self.max_attempts):
            try:
                result = fn()
                if asyncio.iscoroutine(result):
                    result = await result
                return result
            except Exception as exc:  # noqa: BLE001 - filtered by policy
                if not self._should_retry(exc, attempt):
                    raise
                await asyncio.sleep(self._delay(attempt))
        raise RuntimeError("unreachable")  # pragma: no cover

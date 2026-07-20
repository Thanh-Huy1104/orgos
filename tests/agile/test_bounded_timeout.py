"""Tests for §H6 _bounded() helper — asyncio-friendly timeout wrapper.

The bounded helper wraps run_in_executor with asyncio.wait_for so a hung
LLM call unblocks the event loop instead of blocking it forever. Root
cause fix for the "sprint 2 lasted 140 minutes" bug in quant-desk-v3.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock

import pytest

from orgos.agile.agent_loop import _bounded


class TestBoundedTimeout:
    def test_fast_call_returns_normally(self):
        emitter = MagicMock()

        def fast():
            return 42

        result = asyncio.run(_bounded(fast, timeout=5, name="fast", emitter=emitter))
        assert result == 42
        emitter.emit.assert_not_called()

    def test_slow_call_times_out_and_emits_event(self):
        """§H6: bounded returns None (unblocking the coroutine) even though
        the underlying thread cannot be killed. asyncio.run() blocks on
        thread pool shutdown at the end, but the *coroutine* got unblocked.
        """
        emitter = MagicMock()

        async def scenario():
            def slow():
                time.sleep(1.0)
                return "should not reach here"

            start = asyncio.get_event_loop().time()
            result = await _bounded(slow, timeout=0.3, name="hanger", emitter=emitter)
            coroutine_elapsed = asyncio.get_event_loop().time() - start
            return result, coroutine_elapsed

        result, elapsed = asyncio.run(scenario())
        assert result is None
        # The coroutine itself unblocked in ~0.3s (thread continues in background)
        assert elapsed < 1.0, f"coroutine didn't unblock in time (took {elapsed:.2f}s)"
        emitter.emit.assert_called_once()
        call = emitter.emit.call_args
        assert call.args[0] == "ceremony_timeout"
        assert call.kwargs["ceremony"] == "hanger"

    def test_exception_in_call_returns_none_and_emits_error(self):
        emitter = MagicMock()

        def bad():
            raise RuntimeError("boom")

        result = asyncio.run(_bounded(bad, timeout=5, name="boom", emitter=emitter))
        assert result is None
        emitter.emit.assert_called_once()
        assert emitter.emit.call_args.args[0] == "ceremony_error"
        assert "boom" in emitter.emit.call_args.kwargs["error"]

    def test_emitter_failure_doesnt_propagate(self):
        """If the emitter itself is broken, bounded still returns None cleanly."""
        emitter = MagicMock()
        emitter.emit.side_effect = RuntimeError("emitter broken")

        def slow():
            time.sleep(2)

        # Should not raise despite emitter failure
        result = asyncio.run(_bounded(slow, timeout=0.5, name="x", emitter=emitter))
        assert result is None

    def test_concurrent_bounded_calls_isolated(self):
        """Multiple bounded calls don't interfere with each other."""
        emitter = MagicMock()

        def slow(delay):
            time.sleep(delay)
            return delay

        async def run_three():
            results = await asyncio.gather(
                _bounded(lambda: slow(0.1), timeout=2, name="a", emitter=emitter),
                _bounded(lambda: slow(0.2), timeout=2, name="b", emitter=emitter),
                _bounded(lambda: slow(0.3), timeout=2, name="c", emitter=emitter),
            )
            return results

        results = asyncio.run(run_three())
        assert results == [0.1, 0.2, 0.3]

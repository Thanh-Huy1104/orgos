"""Tests for tool-layer tracing — the research trail.

CrewAI 1.14's native function-calling executor never routes tool calls through
step_callback, so we trace at the tool layer. These tests verify the trace fires
on both the direct `_run` path and the `to_structured_tool().func` path the
native executor actually uses, and that `read_trail` reconstructs the trail.
"""

from typing import Any

import pytest
from crewai.tools import BaseTool
from pydantic import BaseModel

from orgos.spawn.governance.audit import AUDIT_DIR, read_trail, trace_tool


class _Args(BaseModel):
    q: str


class _EchoTool(BaseTool):
    name: str = "echo"
    description: str = "echoes its input"
    args_schema: type[BaseModel] = _Args
    tool_category: str = "read"

    def _run(self, q: str) -> str:
        return f"echoed:{q}"


class _BoomTool(BaseTool):
    name: str = "boom"
    description: str = "always raises"
    args_schema: type[BaseModel] = _Args
    tool_category: str = "read"

    def _run(self, q: str) -> str:
        raise RuntimeError("kaboom")


@pytest.fixture
def run_id(request):
    rid = f"trail-test-{request.node.name}"
    (AUDIT_DIR / f"{rid}.jsonl").unlink(missing_ok=True)
    yield rid
    (AUDIT_DIR / f"{rid}.jsonl").unlink(missing_ok=True)


class TestTraceTool:
    def test_direct_run_is_traced(self, run_id):
        t = trace_tool(_EchoTool(), "quant-researcher", run_id)
        assert t._run(q="hello") == "echoed:hello"      # behaviour preserved
        trail = read_trail(run_id)
        assert len(trail) == 1
        rec = trail[0]
        assert rec["role"] == "quant-researcher"
        assert rec["tool"] == "echo"
        assert rec["tool_input"] == {"q": "hello"}
        assert rec["ok"] is True
        assert "echoed:hello" in rec["output_preview"]

    def test_native_structured_path_is_traced(self, run_id):
        # The native executor captures self._run via to_structured_tool().func.
        t = trace_tool(_EchoTool(), "quant-scanner", run_id)
        st = t.to_structured_tool()
        assert st.func(q="world") == "echoed:world"
        trail = read_trail(run_id)
        assert len(trail) == 1
        assert trail[0]["tool_input"] == {"q": "world"}

    def test_exception_is_traced_and_reraised(self, run_id):
        t = trace_tool(_BoomTool(), "quant-scanner", run_id)
        with pytest.raises(RuntimeError, match="kaboom"):
            t._run(q="x")
        trail = read_trail(run_id)
        assert len(trail) == 1
        assert trail[0]["ok"] is False
        assert "kaboom" in trail[0]["output_preview"]

    def test_trail_is_ordered(self, run_id):
        t = trace_tool(_EchoTool(), "r", run_id)
        for q in ("a", "b", "c"):
            t._run(q=q)
        trail = read_trail(run_id)
        assert [r["tool_input"]["q"] for r in trail] == ["a", "b", "c"]

    def test_missing_log_returns_empty(self):
        assert read_trail("no-such-run-id-xyz") == []

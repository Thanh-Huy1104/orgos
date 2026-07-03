import pytest

from orgos.spawn.engine import _enforce_tier, _TierViolation
from orgos.subagents import release_manager_role
from orgos.tools.github_pr_tool import GitHubOpenPRTool


def test_release_with_publish_tool_but_no_approval_fn_fails():
    # Simulate the replay-mode misconfiguration: publish tool attached but
    # the tier expects a gate. Without approval_fn, spawn refuses.
    r = release_manager_role(extra_tools=[GitHubOpenPRTool()])
    with pytest.raises(_TierViolation):
        # The publisher tier's requires_approval=["*"] means every tool must be
        # wired with an approval_fn; the tier enforces this at spawn time.
        _enforce_tier(r)  # noqa: SLF001
        # Actually _enforce_tier does the category/deny checks. The gate check
        # lives in _wire_gates; import and test both.
        from orgos.spawn.engine import _wire_gates
        _wire_gates(r.tools, r, approval_fn=None)

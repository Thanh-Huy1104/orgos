import pytest
from orgos.agile.mutations import (
    SwapBacklogPick, InjectHeuristic, SwapRole, apply_mutation,
)


def _snapshot():
    return {
        "picked_issue": {"issue_id": "1"},
        "backlog": [{"issue_id": "1"}, {"issue_id": "2"}],
        "heuristics": [],
        "role_overrides": {},
    }


def test_swap_backlog_picks_second():
    out = apply_mutation(_snapshot(), SwapBacklogPick(new_issue_id="2"))
    assert out["picked_issue"]["issue_id"] == "2"


def test_swap_backlog_rejects_unknown():
    with pytest.raises(ValueError):
        apply_mutation(_snapshot(), SwapBacklogPick(new_issue_id="99"))


def test_inject_heuristic_appends():
    out = apply_mutation(
        _snapshot(),
        InjectHeuristic(rule="commit early", why="x", tags=["engineer"]),
    )
    assert len(out["heuristics"]) == 1
    assert out["heuristics"][0]["rule"] == "commit early"


def test_swap_role_records_override():
    out = apply_mutation(
        _snapshot(),
        SwapRole(role_name="engineer", alt_model="anthropic/claude-haiku-4-5"),
    )
    assert out["role_overrides"]["engineer"]["model"] == "anthropic/claude-haiku-4-5"
